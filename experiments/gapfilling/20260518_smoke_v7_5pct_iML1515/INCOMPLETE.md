# INCOMPLETE — v7 iML1515 run killed at 30-min cap

**Date**: 2026-05-18
**Status**: ❌ killed at 30:25 elapsed, still inside cobrapy's
post-MILP `validate()` (cobra called `add_metabolites` / `add_reactions`
on the original model and then `slim_optimize` was running). No metrics
files written.

## Reproduce

```
.venv/bin/python -u -m src.gapfill.recovery_runner \
    --model data/iML1515.xml --ratio 0.05 --seed 42 --organism eco \
    --solver gurobi \
    --output experiments/gapfilling/20260518_smoke_v7_5pct_iML1515/
```

Defaults applied (v7): `--solver gurobi`, `--integer-threshold 1e-9`,
reversibility correction ON, **metabolite-compat filter OFF**.

## What got further than v4/v5

- Organism filter completed: 28,301 → 23,742 reactions (within the
  expected 1-5 min budget for filter only).
- cobrapy gap-fill MILP entered with `universal_size=23,742`.
- Gurobi loaded the LP: `1864 rows, 5198 columns, 20214 nonzeros`.
- Then went silent for 28 minutes at 614% CPU (multi-core Gurobi).
  No further progress messages.

## Why it stalled (best guess from log shape)

The user's estimate ("4,664→11 s, so 28,301 should be 1-5 min") assumed
linear scaling. The MILP build phase is linear, but the solver step is
super-linear in the binary count. 23,742 binary indicators is ~5×
v4/v5's 4,664; Gurobi can take much more than 5× the time on the
MIP search. Combined with multi-core 614% CPU it was working, but not
fast enough to fit in the 30-min cap.

## What v7 still proves (qualitative)

- Pipeline modification is correct: metabolite-compat filter was
  successfully bypassed; organism filter still ran; gap-fill received
  the larger universe. Code path is the v6.A fix shape we proposed,
  not regressed.
- Gurobi did NOT instantly return infeasible. It was searching. The
  candidate pool includes the 16 reactions that v6 diagnosis showed
  were dropped — so a feasible solution likely exists (matching
  yesterday's Step-2 manual-restore verification).

## Recommended next step — three branches

1. **Wall budget**: rerun with no time cap (or large cap like 2 h).
   Just measure how long Gurobi actually takes on this MILP at full
   23,742 candidates. If it's > 1 h, the protocol becomes impractical
   for the full 5/10/15% × 5-seed sweep (would total > 60 h).
2. **Gurobi tuning**: pass `time_limit` + `presolve` aggressive,
   `mip_focus=1` (find feasible fast) instead of optimal. The MILP
   does not need the global optimum to validate — first-feasible is
   enough.
3. **Hybrid filter**: keep metabolite-compat filter but only filter
   out reactions that are **safe to drop** (neither in `depleted` nor
   sharing metabolites with the orphan-metabolite producers). Smaller
   than 23,742 but bigger than 4,664. Still reference-free if the
   "safe to drop" criterion never inspects `removed_reaction_ids`.

Option 2 looks like the smallest change. cobrapy passes `**kwargs` to
optlang; we'd pass `time_limit=300, mip_focus=1` and accept the
first feasible solution. Likely 1-5 min as the user originally
expected.

## Files

```
experiments/gapfilling/20260518_smoke_v7_5pct_iML1515/INCOMPLETE.md
```

(No config.json or metrics.json — runner did not reach _write_outputs.)
