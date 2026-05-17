# Run notes

```
recovery_runner v2: model=data/e_coli_core.xml ratio=0.05 seed=42 organism=eco
loading user model...
  user model: 95 rxns, 72 mets
loading universal model via UniversalLoader...
  universal: 28301 rxns, 15638 mets
  reversibility correction: lower_bound -> -1000 on 28301 universal reactions
baseline growth: 0.873922
GPR reactions: 69, sampled to remove: 3
depleted: 92 rxns (growth=-0.000000)
extracting candidates (universal ∖ depleted)...
  candidates: 25372
initializing OrganismFilter for 'eco' (KEGG link/reaction)...
  organism reactions loaded: 0
  filter outcome: accepted=22662 (true+unknown), rejected=2710
building filtered universal model (copy + prune)...
  after organism filter: 22754 rxns (was 28301)
  after metabolite-compat filter: 166 rxns (dropped 22588 reactions using exotic metabolites)
organism filter elapsed: 243.37s
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=166)...
gap-fill done in 0.19s, added=0, failure_mode=infeasible: gap filling optimization failed (infeasible).
metrics: recall=0.000, over_addition=0, growth_diff=0.873922
```

## Re-evaluation under metric framework (design.md §2)

**Run config**: e_coli_core, ratio=0.05, seed=42, GLPK, **reversibility correction ON (v3, 28301 reactions corrected)**.

### Functional family (production-relevant)

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.873922 | reference |
| `depleted_growth` | 0.000000 | `ENO` / `ACONTa` / `ICL` removed |
| `gapfilled_growth` | 0.000000 | gap-fill returned 0 additions |
| `growth_recovery` | **0.000** | functional failure |
| `reaction_overhead` | **0** | nothing added |
| Q1/Q2/Q3/Q4 pass rates | N/A | task suites not yet implemented |
| `failure_mode` | `infeasible` | cobrapy MILP infeasible at lower_bound=0.05 |

### Benchmark family (development-only)

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | 0.000 | identical to v2 result |
| `recovery_precision` | N/A | denominator 0 |
| `recovery_jaccard` | 0.000 | |

### Interpretation

Option A reversibility correction was applied (28301 universal reactions
relaxed) but the outcome is identical to v2. **This is not a bug in the
correction — it confirms a separate failure mode**: e_coli_core is a
95-reaction tutorial model with minimal redundancy. Seed-42's 5% sample
landed on three central-metabolism essentials (`ENO`, `ACONTa`, `ICL`).
A 95-reaction model has no alternative pathway to biomass when those
three are gone — no choice of additions from any universal can rescue
it.

This is a property of the GPR-removal protocol (design.md §6.3
"random samples cutting essential pathways"), not of the tool. The
bound-mismatch fix matters for iML1515 (see
`20260514_smoke_v3_5pct_eco_iML1515/INCOMPLETE.md`); it is a no-op for
e_coli_core under this seed.

Implication: e_coli_core is useful for plumbing validation but not for
measuring gap-fill capability. Restrict capability evaluation to
iML1515 + iMM904 (Phase 2).
