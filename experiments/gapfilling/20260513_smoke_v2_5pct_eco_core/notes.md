# Run notes

```
recovery_runner v2: model=data/e_coli_core.xml ratio=0.05 seed=42 organism=eco
loading user model...
  user model: 95 rxns, 72 mets
loading universal model via UniversalLoader...
  universal: 28301 rxns, 15638 mets
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
organism filter elapsed: 233.35s
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=166)...
gap-fill done in 0.18s, added=0, failure_mode=infeasible: gap filling optimization failed (infeasible).
metrics: recall=0.000, over_addition=0, growth_diff=0.873922
```

## Re-evaluation under metric framework (design.md §2)

**Run config**: e_coli_core, ratio=0.05, seed=42, GLPK, **reversibility correction OFF (v2)**.

### Functional family (production-relevant)

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.873922 | reference |
| `depleted_growth` | 0.000000 | 3 removed reactions (`ENO`, `ACONTa`, `ICL`) block biomass |
| `gapfilled_growth` | 0.000000 | gap-fill returned 0 additions |
| `growth_recovery` (= gapfilled / baseline) | **0.000** | functional failure |
| `reaction_overhead` (= `n_added`) | **0** | nothing added |
| Q1/Q2/Q3/Q4 pass rates | N/A | task suites not yet implemented (design.md §5 Phase 1 step 4) |
| `failure_mode` | `infeasible` | cobrapy MILP infeasible at lower_bound=0.05 |

### Benchmark family (development-only)

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | 0.000 | nothing added → nothing recovered |
| `recovery_precision` | N/A | denominator (`n_added`) is 0 |
| `recovery_jaccard` | 0.000 | |

### Interpretation

Pre-correction baseline. The BiGG universal stored 32.7% of iML1515's
reversible reactions as forward-only — same defect applies to the
e_coli_core run (universal is shared). Gap-fill MILP can't find a
feasible combination because added reactions lack the required
reverse-flux capacity. See
`experiments/audit/20260514_gapfill_diagnosis/notes.md` for the
diagnostic chain that established this.

Note that for e_coli_core specifically, the v3 run (correction ON) ALSO
returned infeasible — this small model has a separate problem (random
5% lands on central-metabolism essentials in a model with no alternative
pathways). The two failure modes coexist for e_coli_core; the bound
mismatch alone does not fully explain its `recovery_recall = 0`.
