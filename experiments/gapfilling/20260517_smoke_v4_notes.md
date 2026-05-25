# v4 smoke runs — Gurobi solver

**Date**: 2026-05-17
**Change**: switch cobrapy gap-fill solver from default GLPK to **Gurobi 12.0.3**.
Reversibility correction (option A) stays on. recovery_runner.py only —
no other `src/` modified.

## Results

### v4 / e_coli_core / 5% / seed 42 (4 min total)

```json
{
  "recovery_recall": 0.0, "recovery_precision": null, "reaction_id_jaccard": 0.0,
  "baseline_growth": 0.873922, "depleted_growth": 0.0, "gapfilled_growth": 0.0,
  "growth_recovery_ratio": 0.0, "reaction_overhead": -3,
  "n_added_reactions": 0,
  "failure_mode": "infeasible: gap filling optimization failed (infeasible).",
  "gapfill_time_sec": 0.223, "elapsed_sec": 226.95,
  "solver": "gurobi", "solver_version": "12.0.3"
}
```

Result identical to v3 (infeasible, recall=0). Confirms again that
e_coli_core 5%/seed42 is genuinely unrecoverable — ENO + ACONTa + ICL
removed, no alternative biomass pathway in a 95-reaction model. Gurobi
returns infeasible decisively in 0.22 s (vs GLPK's 0.19 s in v3 — both
fast for a small infeasible MILP).

### v4 / iML1515 / 5% / seed 42 (3.5 min total)

```json
{
  "recovery_recall": 0.0, "recovery_precision": null, "reaction_id_jaccard": 0.0,
  "baseline_growth": 0.876997, "depleted_growth": 0.0, "gapfilled_growth": 0.0,
  "growth_recovery_ratio": 0.0, "reaction_overhead": -113,
  "n_added_reactions": 0,
  "failure_mode": "error: RuntimeError: Failed to validate gap filled model, try lowering the integer threshold.",
  "gapfill_time_sec": 11.566, "elapsed_sec": 207.33,
  "solver": "gurobi", "solver_version": "12.0.3"
}
```

**Big news**: gap-fill itself takes **11.57 s** (v3 timed out at >20 min
on this exact case). Gurobi solved the MILP — but cobrapy's internal
validation step then rejected the solution. New failure mode, not the
same as v2/v3.

## v2 / v3 / v4 comparison

| Run | Model | Reversibility | Solver | Universe (after filter) | gap-fill time | growth_recovery | recall | failure_mode |
|---|---|---:|---|---:|---:|---:|---:|---|
| v2 | e_coli_core | OFF | GLPK | 166 | 0.18 s | 0.000 | 0.000 | infeasible (bound mismatch) |
| v2 | iML1515 | OFF | GLPK | 4664 | 8.17 s | 0.000 | 0.000 | infeasible (bound mismatch) |
| v3 | e_coli_core | ON  | GLPK | 166 | 0.19 s | 0.000 | 0.000 | infeasible (essentials in 5%) |
| v3 | iML1515 | ON  | GLPK | 4664 | ≥20 min | — | — | timeout |
| **v4** | e_coli_core | ON | **Gurobi 12.0.3** | 166 | 0.22 s | 0.000 | 0.000 | infeasible (essentials in 5%) — same as v3 |
| **v4** | iML1515 | ON | **Gurobi 12.0.3** | 4664 | **11.57 s** | 0.000 | 0.000 | cobrapy validation: "lower integer threshold" |

Interpretation:

- The GLPK timeout (v3 iML1515) is resolved. Gurobi cuts the MILP solve
  from "unbounded" to **11.57 seconds** for the same problem size. This
  is the speed regime needed for the full 5/10/15% × 5-seed sweep.
- The recall=0 / growth=0 outcome is **not** the same failure as v3.
  Gurobi *did* find a solution; cobrapy then re-solved the user model
  with the chosen reactions added and concluded the result doesn't
  meet `lower_bound=0.05` within the integer tolerance. The cobrapy
  error message itself says "try lowering the integer threshold".
- Yesterday's Step-2 diagnostic confirmed a feasible solution exists
  (manual restoration with original iML1515 bounds → 1.0000 × baseline
  growth). So with the right `integer_threshold`, v5 should produce
  the first non-zero recall on this protocol.

## Code changes (recovery_runner.py only)

1. `RunConfig.solver: str = "gurobi"` (default).
2. CLI flag `--solver {gurobi,glpk}`.
3. `_probe_solver_version()` — returns "12.0.3" for Gurobi via
   `gurobipy.gurobi.version()`; "n/a" for GLPK if `swiglpk` import fails.
4. Per-model solver switch (NOT global Configuration): cobra's auto-pick
   chooses Gurobi when available, which broke `universal.copy()` inside
   the metabolite-compat filter (optlang Gurobi `__setstate__` tmp-LP
   round-trip fails). Workaround: force `cobra.Configuration().solver
   = "glpk"` at run start, then `depleted.solver = cfg.solver` right
   before the gap-fill call. universal/filtered stay on GLPK; gap-fill
   builds its MILP on `depleted.solver` so Gurobi handles the heavy work.
5. `RunMetrics` extended with `recovery_precision`, `reaction_id_jaccard`,
   `growth_recovery_ratio`, `reaction_overhead` (signed), `elapsed_sec`,
   `solver`, `solver_version`. metrics.json now reports both metric
   families (design.md §2) plus meta block.

## Suggested next step — v5

Single change: pass `integer_threshold=1e-9` (or `1e-12`) to
`cobra.flux_analysis.gapfilling.gapfill()`. The error message asks for
it directly. Should resolve the validation failure for iML1515.

If v5 still validates as 0, the next move is to inspect the chosen
binary values directly (`gapfiller.indicators` in cobra source) to see
how close the MILP got to the iML1515 baseline solution we verified in
Step-2 of the audit.

## Files (working tree only — not committed per user policy)

```
src/gapfill/recovery_runner.py                                  +v4 deltas
experiments/gapfilling/20260517_smoke_v4_5pct_eco_core/         (config + metrics + notes — complete)
experiments/gapfilling/20260517_smoke_v4_5pct_eco_iML1515/      (config + metrics + notes — complete)
experiments/gapfilling/20260517_smoke_v4_notes.md               (this file)
```

## Design.md update note

`experiments/gapfilling/design.md §6.2` (GLPK timeout — OPEN) can be
closed once v5 produces a clean non-zero recall on iML1515. For now,
v4 establishes that the solver choice was the blocker — design.md §3.4
"planned upgrade to Gurobi" is now the active default in code.

## Time accounting

- Code change + Gurobi copy() workaround: ~10 min
- e_coli_core run: ~4 min (mostly metabolite-compat filter)
- iML1515 run: ~3.5 min
- This notes file: ~5 min
- Total: ~22 min (within 30-min cap)
