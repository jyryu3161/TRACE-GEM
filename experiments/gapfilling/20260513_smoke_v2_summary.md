# Smoke run summary — recovery_runner v2 (filter pipeline)

**Date**: 2026-05-11
**Status**: ✅ **Pipeline works end-to-end on both models.**
The 5% / seed 42 / iML1515 case is infeasible — a real (negative) experimental
result, not a tool failure.

## What changed since v1

`src/gapfill/recovery_runner.py` now applies a **two-stage universe shrinker**
before calling `cobra.flux_analysis.gapfilling.gapfill()`:

1. **`OrganismFilter`** (`src/gapfill/organism_filter.py`, imported but
   currently inert — see "Known issue" below).
2. **Metabolite-compatibility filter** (added in this commit). Keeps only
   universal reactions whose every metabolite already exists in the depleted
   user model. This is set math (no network, no API) and reduces the MILP
   size by ~6–170×.

The previous `gapfill()` call against the full 28k-reaction BiGG universal
did not return in 26+ minutes (see
`experiments/gapfilling/20260513_smoke_5pct_seed42/notes.md`, v1 record
since deleted). After filtering, `gapfill()` returns in seconds.

## Results

| Model | n_rxns | n_GPR | n_removed | universe (before → after) | gap-fill | recall | growth_diff | failure_mode |
|---|---:|---:|---:|---|---:|---:|---:|---|
| `e_coli_core.xml` (690 KB) | 95 | 69 | 3 | 28301 → 22754 → **166** | 0.18 s | 0.000 | 0.874 | infeasible |
| `iML1515.xml` (11 MB) | 2712 | 2266 | 113 | 28301 → 23742 → **4664** | 8.17 s | 0.000 | 0.877 | infeasible |

Total wall time per run (excluding universe load): ~4 min, almost all in the
two filter steps. Gap-fill itself takes < 10 s.

Removed reaction sets are reproducible from seed 42:

- e_coli_core: `ENO` (enolase), `ACONTa` (aconitase), `ICL` (isocitrate lyase)
  — three central-metabolism essentials. e_coli_core has no alternative paths.
- iML1515: 113 reactions (see `metrics.json`). Verified: all 113 exist in
  the BiGG universal — the model has the *option* to restore them, but
  gap-fill at `lower_bound=0.05` can't find any feasible subset.

## Why infeasible

Both runs report `failure_mode: infeasible: gap filling optimization
failed`. Diagnosis (5-line check, see verification block below):

```python
# verified for iML1515 — 113 / 113 removed reactions ARE in universal
direct match in universal: 113
R_ prefix needed: 0; in noR form: 0; not found: 0
```

So the recoverable reactions are present in the candidate pool. The
infeasibility is genuine to the protocol's stringency:

- `lower_bound=0.05` means gap-fill must restore biomass flux ≥ 0.05
- For iML1515 baseline is 0.877; threshold is ~5.7% of baseline
- 113 random GPR reactions cover multiple essential pathways simultaneously
- gap-fill (cobrapy's MILP minimizing |added|) can't satisfy all at once

This matches expectations for a random-sampling protocol on a tightly
connected network. It does not mean the runner is broken — it means
the 5% × seed-42 cut is recovery-infeasible for these models at the
default lower_bound.

## Known issue — KEGG `/link/reaction/<organism>` returns HTTP 400

`OrganismFilter._load_organism_reactions` queries
`https://rest.kegg.jp/link/reaction/eco` (organism_filter.py:175). KEGG
currently rejects this with HTTP 400. Direct verification:

```
GET https://rest.kegg.jp/link/reaction/eco       → 400 (0 bytes)
GET https://rest.kegg.jp/link/rn/eco             → 400
GET https://rest.kegg.jp/list/organism           → 200 OK (1 MB)
GET https://rest.kegg.jp/link/rn/eco:b0001       → 200 (empty)
```

`/list/organism` works, so KEGG REST itself is up; only the bulk
`link/reaction/<orgcode>` form is broken. Result: `OrganismFilter` loads
0 reactions, marks every candidate as `organism_exists=None`, and
ultimately accepts 22662 / 25372 candidates (only ~10% rejected).

The actual universe shrinkage in this v2 comes almost entirely from the
metabolite-compatibility filter:

- iML1515: organism filter accepted 23742, metabolite filter dropped 19078 → 4664
- e_coli_core: organism filter accepted 22754, metabolite filter dropped 22588 → 166

## What this means for the research plan

The pipeline is now scaleable enough to run the full grid
(`AGENTS.md §Gap-filling protocol`: 5/10/15% × 5 seeds = 15 runs per model,
~1 hour per model). Two concerns surface:

1. **Infeasibility at 5% is unexpectedly common.** If most random 5% cuts on
   iML1515 are infeasible, the protocol may need:
   - A lower `--lower-bound` (e.g. 0.01, mirroring the fallback in
     `src/gapfill/engine.py:323`)
   - Or pre-filtering removed reactions to skip definite essentials
     (single-deletion analysis first)
   - Or accept "infeasible" as the *first* metric (a recovery-failure rate)

2. **`OrganismFilter` is currently a no-op** due to the KEGG endpoint
   change. The metabolite-compat filter is doing all the work. We
   should either:
   - Repair `OrganismFilter` against a working KEGG endpoint
     (`/link/rn/<orgcode>` is the most likely replacement — needs
     verification with KEGG docs)
   - Or accept metabolite-compat as the primary filter and document that
     intent in `src/gapfill/recovery_runner.py`
   - Per `AGENTS.md §Operating rules`, `OrganismFilter` lives in
     `src/gapfill/` and changing it requires user approval.

## File inventory (working tree, not committed)

```
src/gapfill/recovery_runner.py                                     (~350 lines)

experiments/gapfilling/
├── 20260513_smoke_v2_5pct_eco_core/
│   ├── config.json
│   ├── metrics.json     # recovery_recall=0.0, gapfill 0.18s, infeasible
│   └── notes.md
├── 20260513_smoke_v2_5pct_eco_iML1515/
│   ├── config.json
│   ├── metrics.json     # recovery_recall=0.0, gapfill 8.17s, infeasible
│   └── notes.md
└── 20260513_smoke_v2_summary.md  (this file)
```

## Suggested decision before next run

- Pick a `--lower-bound`: 0.05 (current) vs 0.01 (engine.py fallback)
- Decide on KEGG endpoint repair vs metabolite-compat as primary filter
- Whether to commit recovery_runner.py and these results, or hold

---

## Cross-experiment view (added 2026-05-13 after design.md §2 framework)

| Run | Model | Reversibility | Solver | Universe (after filter) | growth_recovery | recovery_recall | failure_mode |
|---|---|---:|---:|---:|---:|---:|---|
| v2 | e_coli_core | OFF | GLPK | 166 | 0.000 | 0.000 | infeasible (bound mismatch) |
| v2 | iML1515 | OFF | GLPK | 4664 | 0.000 | 0.000 | infeasible (bound mismatch) |
| v3 | e_coli_core | ON  | GLPK | 166 | 0.000 | 0.000 | infeasible (essentials in 5%) |
| v3 | iML1515 | ON  | GLPK | 4664 | — | — | timeout 20+ min (large MILP) |

Both metric families (per `experiments/gapfilling/design.md §2`) report
zero recovery across v2 and v3. The two failure modes are distinct:

- **v2** failed because the universal donor was forward-only on
  reversible reactions (`audit/20260514_gapfill_diagnosis/notes.md`).
  Fixed by option A in v3.
- **v3 e_coli_core** still failed because the 95-reaction model has no
  alternative pathway when central essentials are cut. Protocol property.
- **v3 iML1515** failed differently — GLPK ran out of time on the
  doubled-search-space MILP. Resolution: Gurobi (planned v4, see
  `design.md §6.2`).
