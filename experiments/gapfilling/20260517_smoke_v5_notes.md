# v5 smoke runs — integer_threshold loosened

**Date**: 2026-05-17
**Change**: pass `integer_threshold=1e-9` to gap-fill, via `GapFiller`
class directly (cobra's convenience `gapfill()` doesn't expose this
arg in 0.30). Per supervisor request after v4's validation error.
recovery_runner.py only.

## Results

### v5 / e_coli_core / 5% / seed 42 (~4 min total)

```json
{
  "recovery_recall": 0.0, "recovery_precision": null, "reaction_id_jaccard": 0.0,
  "baseline_growth": 0.873922, "depleted_growth": 0.0, "gapfilled_growth": 0.0,
  "growth_recovery_ratio": 0.0, "reaction_overhead": -3, "n_added_reactions": 0,
  "failure_mode": "infeasible: gap filling optimization failed (infeasible).",
  "gapfill_time_sec": 0.263, "elapsed_sec": 230.21,
  "solver": "gurobi", "solver_version": "12.0.3"
}
```

Identical to v4 e_coli_core. Sanity check confirms the GapFiller direct
call works; the failure here remains the essentiality issue
(`ENO`/`ACONTa`/`ICL` cut → no biomass path in a 95-reaction model).

### v5 / iML1515 / 5% / seed 42 (~4.6 min total) — **integer_threshold did NOT fix it**

```json
{
  "recovery_recall": 0.0, "recovery_precision": null, "reaction_id_jaccard": 0.0,
  "baseline_growth": 0.876997, "depleted_growth": 0.0, "gapfilled_growth": 0.0,
  "growth_recovery_ratio": 0.0, "reaction_overhead": -113, "n_added_reactions": 0,
  "failure_mode": "error: RuntimeError: Failed to validate gap filled model, try lowering the integer threshold.",
  "gapfill_time_sec": 86.73, "elapsed_sec": 278.39,
  "solver": "gurobi", "solver_version": "12.0.3"
}
```

Same error message as v4. **Gap-fill time went UP** (11.57 s → 86.73 s)
because the tighter threshold expanded the candidate-inclusion set,
making the validate step's re-solve slower.

## v2 / v3 / v4 / v5 comparison

| Run | Model | Reversibility | Solver | integer_threshold | gap-fill time | growth_recovery | recall | failure_mode |
|---|---|---:|---|---:|---:|---:|---:|---|
| v2 | e_coli_core | OFF | GLPK | 1e-6 (default) | 0.18 s | 0.000 | 0.000 | infeasible (bound mismatch) |
| v2 | iML1515 | OFF | GLPK | 1e-6 | 8.17 s | 0.000 | 0.000 | infeasible (bound mismatch) |
| v3 | e_coli_core | ON | GLPK | 1e-6 | 0.19 s | 0.000 | 0.000 | infeasible (essentials in 5%) |
| v3 | iML1515 | ON | GLPK | 1e-6 | ≥20 min | — | — | timeout |
| v4 | e_coli_core | ON | Gurobi | 1e-6 | 0.22 s | 0.000 | 0.000 | infeasible (essentials in 5%) |
| v4 | iML1515 | ON | Gurobi | 1e-6 | 11.57 s | 0.000 | 0.000 | validate failed |
| **v5** | e_coli_core | ON | Gurobi | **1e-9** | 0.26 s | 0.000 | 0.000 | infeasible (essentials in 5%) — same |
| **v5** | iML1515 | ON | Gurobi | **1e-9** | **86.73 s** | 0.000 | 0.000 | **validate failed (same error)** |

## What I learned by reading cobra source

`GapFiller.fill()` (cobra 0.30, `flux_analysis/gapfilling.py`):

```python
solution = [
    self.model.reactions.get_by_id(ind.rxn_id)
    for ind in self.indicators
    if ind._get_primal() > self.integer_threshold
]
if not self.validate(solution):
    raise RuntimeError("Failed to validate gap filled model, ...")
```

`GapFiller.validate()`:

```python
with self.original_model as model:
    mets = [x.metabolites for x in reactions]
    all_keys = set().union(*(d.keys() for d in mets))
    model.add_metabolites(all_keys)
    model.add_reactions(reactions)
    model.slim_optimize()
    return (model.solver.status == OPTIMAL
            and model.solver.objective.value >= self.lower_bound)
```

- A reaction is selected if its indicator's primal value exceeds
  `integer_threshold`. Lower threshold → more reactions selected.
- Validation then **adds those reactions** to the original model and
  re-optimises. Success requires `objective ≥ lower_bound`.
- v5 lowered the threshold to 1e-9. More reactions were thus selected
  (gap-fill time went up because validate re-solves on a larger set),
  but the chosen reactions still don't restore growth ≥ 0.05.

So the bottleneck is **not the threshold**: the MILP simply did not
pick the *correct* reactions. The candidates available to the MILP must
not contain the right set.

## New hypothesis (untested) — metabolite-compat filter is too aggressive

`recovery_runner.py:_filter_universal_to_organism` runs a
metabolite-compatibility filter:

```python
incompatible = [
    r for r in filtered.reactions
    if not all(m.id in depleted_metabolite_ids for m in r.metabolites)
]
filtered.remove_reactions(incompatible, remove_orphans=True)
```

When we deplete iML1515, `remove_orphans=True` drops 13 metabolites
(verified: `step1_summary.json`). The universal versions of removed
reactions that **used those 13 orphaned metabolites** would then fail
the metabolite-compat filter and be dropped from the candidate pool.

Yesterday's Step-2 diagnostic restored growth by adding the universal
reactions directly to a depleted-but-NOT-metabolite-compat-filtered
model. `cobra.Model.add_reactions()` re-introduces metabolites when
needed. So that path worked. Our gap-fill path doesn't — the filter
removed the necessary candidates before the MILP could see them.

## Suggested next step — v6

**Hypothesis to test**: confirm whether the metabolite-compat filter
removes any of the 113 removed-reaction IDs from the candidate pool.

Quick diagnostic (no production code change):
1. Load iML1515, sample seed=42 5%, deplete with `remove_orphans=True`.
2. Compute filtered universe (current metabolite-compat logic).
3. Check `113 ∩ filtered_universe.reactions` — if < 113, that's the
   smoking gun.

If confirmed, **two production fixes**:

- **6.A** — Deplete with `remove_orphans=False`. Keeps metabolites that
  were unique to removed reactions present in depleted, so universal
  versions pass the metabolite-compat filter. Side-effect: orphan
  metabolites stay in the depleted model with no producer/consumer.
- **6.B** — Soften metabolite-compat: require only that *some*
  metabolites overlap with depleted, not all. Less surgical but
  needed if removed reactions introduce metabolites entirely absent
  from depleted.

Either fix is reference-free (uses only depleted's metabolite IDs,
never `removed_reaction_ids`) and therefore compliant with
`AGENTS.md §Gap-filling protocol`.

## Code changes (v5 specifically)

`src/gapfill/recovery_runner.py` only:

1. `RunConfig.integer_threshold: float = 1e-9` (new field).
2. CLI flag `--integer-threshold` (default `1e-9`).
3. Gap-fill call: replaced the convenience `cobra_gapfill(...)` with
   `GapFiller(..., integer_threshold=cfg.integer_threshold).fill(iterations=1)`
   because cobra 0.30's `gapfill()` wrapper doesn't expose this parameter
   even though the underlying class does.

## Time accounting

- Code patch + sig-mismatch fix (GapFiller direct call): ~6 min
- e_coli_core run: ~4 min
- iML1515 run: ~5 min
- Reading cobra source + writing this analysis: ~5 min
- Total: ~20 min (at cap)

## Files (working tree only — not committed per user policy)

```
src/gapfill/recovery_runner.py                                  +integer_threshold + GapFiller direct call
experiments/gapfilling/20260517_smoke_v5_5pct_eco_core/         (config + metrics + notes — complete)
experiments/gapfilling/20260517_smoke_v5_5pct_eco_iML1515/      (config + metrics + notes — complete)
experiments/gapfilling/20260517_smoke_v5_notes.md               (this file)
```
