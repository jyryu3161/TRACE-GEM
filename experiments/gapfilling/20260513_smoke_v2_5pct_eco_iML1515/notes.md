# Run notes

```
recovery_runner v2: model=data/iML1515.xml ratio=0.05 seed=42 organism=eco
loading user model...
  user model: 2712 rxns, 1877 mets
loading universal model via UniversalLoader...
  universal: 28301 rxns, 15638 mets
baseline growth: 0.876997
GPR reactions: 2266, sampled to remove: 113
depleted: 2599 rxns (growth=0.000000)
extracting candidates (universal ∖ depleted)...
  candidates: 23193
initializing OrganismFilter for 'eco' (KEGG link/reaction)...
  organism reactions loaded: 0
  filter outcome: accepted=21155 (true+unknown), rejected=2038
building filtered universal model (copy + prune)...
  after organism filter: 23742 rxns (was 28301)
  after metabolite-compat filter: 4664 rxns (dropped 19078 reactions using exotic metabolites)
organism filter elapsed: 195.70s
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=4664)...
gap-fill done in 8.17s, added=0, failure_mode=infeasible: gap filling optimization failed (infeasible).
metrics: recall=0.000, over_addition=0, growth_diff=0.876997
```

## Re-evaluation under metric framework (design.md §2)

**Run config**: iML1515, ratio=0.05, seed=42, GLPK, **reversibility correction OFF (v2)**.

### Functional family (production-relevant)

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.876997 | wild-type FBA |
| `depleted_growth` | 0.000000 | 113/2266 GPR reactions removed |
| `gapfilled_growth` | 0.000000 | gap-fill returned 0 additions |
| `growth_recovery` | **0.000** | functional failure |
| `reaction_overhead` | **0** | nothing added |
| Q1/Q2/Q3/Q4 pass rates | N/A | task suites not yet implemented |
| `failure_mode` | `infeasible` | cobrapy MILP infeasible at lower_bound=0.05 |

### Benchmark family (development-only)

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | 0.000 | 0/113 of removed reactions added back |
| `recovery_precision` | N/A | denominator 0 |
| `recovery_jaccard` | 0.000 | |

### Interpretation

**Root cause confirmed (this run is the trigger)**: 37/113 (32.7%) of
the removed reactions are stored as forward-only in BiGG universal but
reversible in iML1515. cobrapy `gapfill()` adds reactions with universal
bounds, so the recovered model is missing essential reverse fluxes →
infeasible.

Full diagnostic chain in
`experiments/audit/20260514_gapfill_diagnosis/notes.md`:

- Step 1 (manual restore from universal): growth = 0 → not a solver issue.
- Step 2 (manual restore with original iML1515 bounds): growth = baseline,
  ratio 1.0000 → bounds were the bottleneck.

Resolution applied in v3 (`20260514_smoke_v3_5pct_eco_iML1515/`).
