# INCOMPLETE — iML1515 v3 run killed at 30-min cap

**Date**: 2026-05-13
**Status**: ❌ killed at 20:35 elapsed in cobrapy `gapfill()`. No metrics files written.

## Reproduce

```
.venv/bin/python -u -m src.gapfill.recovery_runner \
    --model data/iML1515.xml --ratio 0.05 --seed 42 --organism eco \
    --output experiments/gapfilling/20260514_smoke_v3_5pct_eco_iML1515/
```

## Why it didn't finish

After reversibility correction, **all 28301 universal reactions** have
`lower_bound=-1000`. The MILP that cobrapy `gapfill()` builds doubles in
effective variable freedom (each binary now permits forward OR reverse
flow). Same filtered universe size as v2 (4664 rxns), but ~150× longer
solve time and counting.

Last log line before kill: `running cobra.flux_analysis.gapfilling.gapfill(
lower_bound=0.05, universal_size=4664)...` then 20:35 of silent solver
loop at 100% CPU.

## Compare: v2 (no correction) finished in 8.17 s

The fix that addresses the recall=0 root cause also turns the gap-fill
MILP from "fast and infeasible" into "slow but in-principle feasible".
For iML1515 this is too slow with default GLPK.

See `experiments/gapfilling/20260514_smoke_v3_notes.md` for the v2 ↔ v3
comparison table and recommended next step (targeted correction:
restore reversibility on **only the candidate set**, not all 28301).

## Re-evaluation under metric framework (design.md §2)

**Run config**: iML1515, ratio=0.05, seed=42, GLPK, **reversibility correction ON (v3, 28301 reactions corrected)**.

### Functional family (production-relevant)

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.876997 | (from earlier v2 run; not re-measured) |
| `depleted_growth` | — | reached but not recorded (killed before write) |
| `gapfilled_growth` | — | gap-fill did not return |
| `growth_recovery` | — | indeterminate |
| `reaction_overhead` | — | indeterminate |
| Q1/Q2/Q3/Q4 pass rates | N/A | task suites not yet implemented |
| `failure_mode` | `timeout` | GLPK in gap-fill phase ≥ 20 min at 100% CPU; killed at cap |

### Benchmark family (development-only)

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | — | unknown; gap-fill never returned |
| `recovery_precision` | — | |
| `recovery_jaccard` | — | |

### Interpretation

Option A (reversibility correction) succeeded mechanically — every
universal reaction with `upper_bound > 0` had its `lower_bound` set to
`-1000`, count `n_universal_reversibility_corrected = 28301`. The
filtered universe size matched v2 (4664 reactions; metabolite-compat
filter is deterministic) but the MILP search space effectively doubled
because each candidate now has reverse-flow capacity.

Yesterday's Step-2 diagnostic confirmed that a feasible solution
**exists** (manual restoration with original bounds → 1.0000 × baseline
growth). GLPK simply cannot find it within the time budget.

Resolution path (design.md §6.2): switch to Gurobi. Until then, ratios
beyond 5% on iML1515 are expected to time out under v3.
