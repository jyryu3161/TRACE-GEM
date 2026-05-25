# v7 smoke notes — metabolite-compat filter disabled

**Date**: 2026-05-18
**Change**: per supervisor guidance, **disable the metabolite-compat
filter** that v6 diagnosis showed was dropping 16/113 of the removed
reactions from the candidate pool. recovery_runner.py only.

## Status

- Code change: ✅ deployed and verified (new CLI flag works).
- iML1515 5%/seed42 run: ❌ killed at 30-min cap, inside Gurobi's MILP
  search on the larger candidate pool (23,742 reactions). See
  `20260518_smoke_v7_5pct_iML1515/INCOMPLETE.md`.

## Code changes (recovery_runner.py only)

1. `RunConfig.use_metabolite_compat_filter: bool = False` (new field,
   default OFF in v7+).
2. CLI flag `--use-metabolite-compat-filter` (store_true) — reproduces
   v3-v6 behaviour for comparison.
3. `_filter_universal_to_organism` takes `use_metabolite_compat` arg
   and wraps the old filter in `if use_metabolite_compat:`.
4. metrics JSON adds aliases `n_universal_reactions` and
   `n_candidate_reactions` (same numbers as the existing
   `n_universal_before_filter` / `n_universal_after_filter`, just
   the names the supervisor asked for in the brief).

## Comparison table (v2 → v7)

| Run | Model | Reversibility | Solver | int_thr | metab-compat | candidates | gap-fill time | growth_recovery | recall | failure_mode |
|---|---|---|---|---:|---|---:|---:|---:|---:|---|
| v2 | iML1515 | OFF | GLPK | 1e-6 | ON | 4664 | 8.17 s | 0.000 | 0.000 | infeasible (bound mismatch) |
| v3 | iML1515 | ON | GLPK | 1e-6 | ON | 4664 | ≥20 min | — | — | timeout |
| v4 | iML1515 | ON | Gurobi | 1e-6 | ON | 4664 | 11.57 s | 0.000 | 0.000 | validate failed |
| v5 | iML1515 | ON | Gurobi | 1e-9 | ON | 4664 | 86.73 s | 0.000 | 0.000 | validate failed |
| v6 | (diagnostic — no run) | — | — | — | — | — | — | — | — | filter drops 16/113 |
| **v7** | iML1515 | ON | Gurobi | 1e-9 | **OFF** | **23,742** | killed @ 30 min | — | — | timeout (Gurobi still searching) |

| Run | Model | candidates | gap-fill time | failure_mode |
|---|---|---:|---:|---|
| v2 | e_coli_core | 166 | 0.18 s | infeasible (essentials) |
| v3 | e_coli_core | 166 | 0.19 s | infeasible (essentials) |
| v4 | e_coli_core | 166 | 0.22 s | infeasible (essentials) |
| v5 | e_coli_core | 166 | 0.26 s | infeasible (essentials) |
| v7 | e_coli_core | (not run this round) | | |

## Interpretation

The v6 diagnosis isolated the wrong filter. v7 confirms the new tradeoff:

- **v4/v5 (filter ON)**: candidate pool 4,664, fast MILP, but missing
  16/113 essential reactions → validate fails.
- **v7 (filter OFF)**: candidate pool 23,742, has all 113 essential
  reactions, MILP is feasible in principle, but solver doesn't finish
  in 30 min.

So both endpoints fail differently. Yesterday's Step-2 manual restore
proved a feasible solution exists; the issue is now compute time.

## Recommended next step

Three branches in priority order (cheapest first):

### F.1 — Gurobi tuning: `mip_focus=1`, `time_limit=300`

cobrapy's `GapFiller` exposes `**kwargs` that go to optlang/Gurobi
parameters. Try:

```python
gapfiller = GapFiller(
    depleted, universal=target_universal,
    lower_bound=cfg.lower_bound,
    integer_threshold=cfg.integer_threshold,
    demand_reactions=True, exchange_reactions=False,
    time_limit=300,    # 5-min wall clock per iteration
    mip_focus=1,       # find feasible fast; don't seek global optimum
)
```

If `**kwargs` doesn't flow through, set on the underlying solver:
`depleted.solver.configuration.timeout = 300`.

We don't need optimality for this protocol — first feasible solution
that validates is sufficient (per design.md §2 production metric is
growth recovery, not minimum addition count).

### F.2 — hybrid filter

Keep the filter but exempt reactions whose missing metabolites are
*known orphans*. Reference-free criterion:

```python
# orphan_mets = metabolites in original model but NOT in depleted
orphan_mets = orig_metabolite_ids - depleted_metabolite_ids
allowed_missing = orphan_mets  # only forgive these specific orphans
incompatible = [
    r for r in filtered.reactions
    if any(
        m.id not in depleted_metabolite_ids and m.id not in allowed_missing
        for m in r.metabolites
    )
]
```

This drops fewer reactions than the current filter (keeps the 16) but
still excludes universal-only metabolites the model never had. Candidate
pool size estimated 5,000-8,000 — middle ground between 4,664 and
23,742.

### F.3 — `remove_orphans=False` during deplete

The original v6 fix proposal. Eliminates the orphan-metabolite problem
at the source: depleted keeps all 1877 metabolites, so the
metabolite-compat filter passes the 16 universal reactions. Candidate
pool stays ~4,680. Fast Gurobi solve (back to v4 timing).

The orphan metabolites sit in depleted with no producer or consumer —
inert from FBA's perspective. Same effect as yesterday's audit Step-2
manual restoration, which gave 1.0000 × baseline growth.

**My recommendation**: try F.3 first (smallest change, restores fast
solve, gives a known feasible solution per audit Step-2). If F.3 still
fails validate(), fall back to F.1.

## Files

```
src/gapfill/recovery_runner.py                                              +v7 deltas
experiments/gapfilling/20260518_smoke_v7_5pct_iML1515/INCOMPLETE.md
experiments/gapfilling/20260518_smoke_v7_notes.md                           (this file)
```

## Time

- Code patch: ~8 min
- iML1515 run (killed at cap): 30 min
- This writeup: ~5 min
- Total: ~43 min (over 30-min cap; stopped on the cap rule per the brief).
