# v7_retry consolidated notes — 60-min budget removed, iML1515 + e_coli_core

**Date**: 2026-05-18
**Trigger**: v7 (2026-05-18 14:21) was killed at the 30-min cap before
Gurobi could finish. Supervisor extended the cap to ~15.5 h (Tuesday
10am) and asked for a parallel e_coli_core sanity check.

## Headline result

- **v7_retry iML1515**: finished naturally at **58.3 min** (`elapsed_sec
  3558.29`). NOT a timeout. But cobrapy `validate()` rejected the
  Gurobi solution with the same error as v4/v5 ("try lowering the
  integer threshold").
  → `failure_mode: error`, `recall: 0.000`, `n_added: 0`.
  → File: `20260518_smoke_v7_retry_5pct_iML1515/notes.md`.

- **v7 e_coli_core (parallel)**: finished in **6.4 min**.
  `failure_mode: ok` (first OK in the series), but
  `growth_recovery_ratio = 5.5088` (non-physical, ~5.5× wild-type
  biomass — Gurobi exploited an energy-generating cycle the
  reversibility correction enabled).
  → recall still 0; the 2 reactions Gurobi added are *not* the 3
  removed.
  → File: `20260518_smoke_v7_eco_core/notes.md`.

So: **the filter removal made the pipeline produce numerical answers
on both models for the first time**, but neither answer is the
"recovered original" the protocol asks for.

## v2 → v7 retry comparison (iML1515)

| Run | rev-corr | solver | int_thr | metab-compat | candidates | gap-fill time | failure_mode | n_added | recall |
|---|---|---|---:|---|---:|---:|---|---:|---:|
| v2 | OFF | GLPK | 1e-6 | ON | 4664 | 8.17 s | infeasible (bound mismatch) | 0 | 0.000 |
| v3 | ON  | GLPK | 1e-6 | ON | 4664 | ≥20 min | timeout | — | — |
| v4 | ON  | Gurobi | 1e-6 | ON | 4664 | 11.57 s | validate failed | 0 | 0.000 |
| v5 | ON  | Gurobi | 1e-9 | ON | 4664 | 86.73 s | validate failed | 0 | 0.000 |
| v7 (30m cap) | ON | Gurobi | 1e-9 | OFF | 23,742 | killed @ 30 min | timeout | — | — |
| **v7_retry** | ON | Gurobi | 1e-9 | OFF | 23,742 | 3500.99 s | **validate failed** | 0 | 0.000 |

## v2 → v7 retry comparison (e_coli_core)

| Run | rev-corr | solver | metab-compat | candidates | gap-fill time | failure_mode | n_added | recall | growth_ratio |
|---|---|---|---|---:|---:|---|---:|---:|---:|
| v2 | OFF | GLPK | ON | 166 | 0.18 s | infeasible (bound mismatch) | 0 | 0.000 | 0.000 |
| v3 | ON | GLPK | ON | 166 | 0.19 s | infeasible (essentials in 5%) | 0 | 0.000 | 0.000 |
| v4 | ON | Gurobi | ON | 166 | 0.22 s | infeasible (essentials in 5%) | 0 | 0.000 | 0.000 |
| v5 | ON | Gurobi | ON | 166 | 0.26 s | infeasible (essentials in 5%) | 0 | 0.000 | 0.000 |
| **v7** | ON | Gurobi | OFF | 22,754 | 245.77 s | **ok** | 2 | 0.000 | **5.5088** |

## Two distinct failure modes now observed

1. **Validation rejection (iML1515)**: Gurobi picks reactions; when
   cobra builds the original model with those reactions and re-solves,
   growth doesn't reach `lower_bound=0.05`. The MILP "answer" is
   numerically marginal or relies on shortcuts only available inside
   the MILP's relaxed copy.
2. **Non-physical pass (e_coli_core)**: Gurobi picks reactions that
   *do* yield growth ≥ 0.05 in validation, but the growth value is
   5.5× the baseline — a thermodynamic shortcut produced by the
   reversibility correction. cobrapy passes the run as "ok" because
   there is no thermodynamic check at the validation step.

Both failures point at the same root: **the protocol's MILP objective
(minimise reactions added) finds clever shortcuts in the
reversibility-corrected universal that have nothing to do with
restoring the originals.** A correct production gap-fill needs
either (a) Q1/Q2 quality tests to filter out non-physical solutions,
or (b) a different MILP objective that penalises shortcuts.

## Pipeline state

- recovery_runner.py is the v7 codebase. No `src/` files outside it
  modified during this round.
- All v2/v3/v4/v5/v7 result directories are in `experiments/gapfilling/`.
- Working tree is uncommitted; user reviews before commit per policy.

## Suggested next steps for the morning (Tuesday)

Priority order, cheapest first. None of these require src/ changes
outside recovery_runner.py.

1. **Implement Q1/Q2 quality probes inline** (no new tests/ files
   yet, just inline in recovery_runner): after `validate()` succeeds,
   run an EGC check and an ATP-yield check on the gap-filled model.
   Flag results as `q1_egc_pass`, `q2_atp_pass`. This re-classifies
   e_coli_core v7's "ok" as a Q1 failure and gives the production
   metric AGENTS.md §Goal asks for.

2. **Raise `lower_bound` to 0.10**. If iML1515 v8 still validate-fails
   at 0.10, the issue is structural (MILP doesn't have a path to
   solid growth from the filtered pool). If it succeeds at 0.10, the
   v4-v5-v7 failures were numerical-marginal.

3. **Capture MILP indicator values** before `validate()`. A 10-line
   addition to the runner to dump `[ind._get_primal() for ind in
   gapfiller.indicators]`. Tells us exactly what Gurobi tried before
   cobrapy rejected it.

4. **Try `--lower-bound 0.5`** for iML1515. The Step-2 audit verified
   `growth = 0.877` is achievable with the original 113 reactions, so
   0.5 still has a feasible target.

5. **Wider sweep**: now that one (model, ratio, seed) finishes inside
   one hour for both models, try seeds 43-46 in parallel to see if
   the failure mode is seed-specific or structural.

## Time accounting

- v7_retry iML1515: 58.3 min (natural completion)
- v7 e_coli_core (parallel): 6.4 min
- Monitoring + writeup: ~30 min spread across polling intervals
- Total wall clock on this round: ~1 h

## Files added by this round (working tree, not committed)

```
experiments/gapfilling/
├── 20260518_smoke_v7_retry_5pct_iML1515/
│   ├── config.json
│   ├── metrics.json   (failure_mode: validate-failed)
│   └── notes.md       (overlay analysis)
├── 20260518_smoke_v7_eco_core/
│   ├── config.json
│   ├── metrics.json   (failure_mode: ok, growth 5.5×)
│   └── notes.md       (overlay analysis)
└── 20260518_smoke_v7_retry_notes.md   (this file — top-level summary)
```
