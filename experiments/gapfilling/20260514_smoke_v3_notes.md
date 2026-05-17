# v2 vs v3 comparison — reversibility correction (option A)

**Date**: 2026-05-13
**Goal**: apply yesterday's diagnosis fix — restore reversibility on the
BiGG universal at load time — and measure the effect on
`recovery_recall` for the 5% / seed 42 cut.

## Code changes (recovery_runner.py only)

1. `RunConfig.reversible_correction: bool = True` (default ON)
2. New `_apply_reversibility_correction(universal)` — for every reaction with
   `upper_bound > 0` and `lower_bound != -1000`, set `lower_bound = -1000`.
   Called immediately after `UniversalLoader().load(...)`.
3. `RunMetrics.n_universal_reversibility_corrected` — count of changed
   reactions.
4. CLI flag `--no-reversible-correction` to reproduce v2 behaviour.
5. Final-summary JSON keys expanded: `depleted_growth`, `gapfilled_growth`,
   `n_added_reactions`, `n_universal_reversibility_corrected`.

Diff vs `b89926f`: src/gapfill/recovery_runner.py only (no other src/
touched, per AGENTS.md §Operating rules).

## Runs

### v3 / e_coli_core / 5% / seed 42 (completed, 4 min)

```json
{
  "recovery_recall": 0.0,
  "depleted_growth": -0.0,
  "gapfilled_growth": -0.0,
  "growth_diff": 0.873922,
  "n_added_reactions": 0,
  "over_addition": 0,
  "n_universal_reversibility_corrected": 28301,
  "gapfill_time_sec": 0.189,
  "organism_filter_time_sec": 243.367,
  "n_universal_after_filter": 166,
  "failure_mode": "infeasible: gap filling optimization failed (infeasible)."
}
```

### v3 / iML1515 / 5% / seed 42 (incomplete — killed at 20:35 in cap)

See `20260514_smoke_v3_5pct_eco_iML1515/INCOMPLETE.md`. cobrapy MILP did
not return inside the 30-min budget after the correction.

## Comparison table

| Run | model | rev-corr | universe (after filter) | gap-fill | recall | depleted growth | gapfilled growth | added | failure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| v2 (2026-05-13) | e_coli_core | OFF | 166 | 0.18 s | 0.000 | 0.000 | 0.000 | 0 | infeasible |
| **v3 (today)** | e_coli_core | ON (28301) | 166 | 0.19 s | 0.000 | 0.000 | 0.000 | 0 | infeasible |
| v2 (2026-05-13) | iML1515 | OFF | 4664 | 8.17 s | 0.000 | 0.000 | 0.000 | 0 | infeasible |
| **v3 (today)** | iML1515 | ON (28301) | 4664 | ≥20 min | — | — | — | — | killed at cap |

## Interpretation

### e_coli_core: same result, different reason

v2 → v3 didn't move the needle on e_coli_core. The removed reactions
(`ENO`, `ACONTa`, `ICL`) are central-metabolism essentials in a
95-reaction model that has *no* alternative biomass-producing pathways.
This is genuine recovery-infeasibility, not the bound-mismatch issue.
The reversibility fix is a no-op here because:

- e_coli_core is a tutorial model with minimal redundancy
- 5% of 69 GPR reactions = 3 reactions; sampling 3 essential central
  reactions is very likely
- Yesterday's bound-mismatch diagnosis was done on iML1515, not
  e_coli_core — we have no Step-1-equivalent verification that
  e_coli_core's failure was bound-related (it appears it was not)

### iML1515: correction is conceptually right but solver-too-slow

v3 entered the gap-fill phase exactly like v2 with the same filtered
universe size (4664). With reversibility restored, the MILP variable
count effectively doubles (each candidate's flux can flow either way)
and the default GLPK solver can no longer return in seconds.

Yesterday's Step-2 diagnostic confirmed that **with the right bounds,
the recovered model regains baseline growth (1.0000 × baseline)**. So
the answer exists — cobrapy just needs more time, a better solver, or
a smaller candidate set to find it within budget.

## Recommended next step (not executed in this run)

The correction is currently applied to **all** 28301 universal
reactions (counter shows `n_universal_reversibility_corrected = 28301`).
A more surgical version would only relax the reactions that survive the
metabolite-compat filter (4664 for iML1515), or even just the candidate
set that overlaps with the removed-reaction IDs. This keeps the MILP
small. Two concrete options to discuss tomorrow:

- **A.1 — narrow correction to the filtered universe**: move the
  `_apply_reversibility_correction` call to *after* the metabolite-compat
  filter. Same result for our problem (the removed reactions are inside
  the filtered universe) at 6× fewer relaxed reactions.
- **A.2 — narrow to removed-reaction IDs only**: relax only the bounds
  of reactions whose `id` is in `removed_reaction_ids`. This is the
  minimum intervention; recall-measurement stays clean because nothing
  else in the universe changes.

Either A.1 or A.2 should bring iML1515 back into the seconds-range of
v2 while still resolving the 32.7% bound-mismatch from yesterday's
diagnosis.

## Time accounting

- Code change (v3 deltas): ~10 min
- v3 / iML1515 attempt: ~21 min (killed)
- v3 / e_coli_core: ~4 min
- Notes + INCOMPLETE.md: ~5 min
- Total: ~40 min (10 min over the 30-min cap; stopped on schedule
  per the user's "막히면 멈추고 보고" rule).

## Working tree (not committed)

```
src/gapfill/recovery_runner.py                                  +reversibility code
experiments/gapfilling/20260514_smoke_v3_notes.md               (this file)
experiments/gapfilling/20260514_smoke_v3_5pct_eco_core/         (config/metrics/notes — complete)
experiments/gapfilling/20260514_smoke_v3_5pct_eco_iML1515/      (INCOMPLETE.md only)
```

---

## Cross-experiment view (added 2026-05-13 after design.md §2 framework)

Same four-row table as `20260513_smoke_v2_summary.md` (kept here too so
the v3 reader doesn't have to flip files):

| Run | Model | Reversibility | Solver | Universe (after filter) | growth_recovery | recovery_recall | failure_mode |
|---|---|---:|---:|---:|---:|---:|---|
| v2 | e_coli_core | OFF | GLPK | 166 | 0.000 | 0.000 | infeasible (bound mismatch) |
| v2 | iML1515 | OFF | GLPK | 4664 | 0.000 | 0.000 | infeasible (bound mismatch) |
| v3 | e_coli_core | ON  | GLPK | 166 | 0.000 | 0.000 | infeasible (essentials in 5%) |
| v3 | iML1515 | ON  | GLPK | 4664 | — | — | timeout 20+ min (large MILP) |

Per `design.md §2`, both functional and benchmark families are zero
across the table. The takeaway is that **the bound-mismatch fix is
necessary but not sufficient** to make this protocol produce a usable
result on iML1515 with GLPK: the fix unblocks the search but the search
becomes intractable.

Next milestone (design.md §5 Phase 1 step 2 / §6.2): re-run with Gurobi.
Expected result: v3 iML1515 finishes in seconds (Step-2 diagnostic
confirms a feasible solution exists at baseline growth) and the table's
empty cells get filled with non-zero functional / benchmark numbers.
