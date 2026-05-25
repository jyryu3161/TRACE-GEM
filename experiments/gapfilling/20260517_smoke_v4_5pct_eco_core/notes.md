# Run notes

```
recovery_runner v4: model=data/e_coli_core.xml ratio=0.05 seed=42 organism=eco solver=gurobi (v12.0.3)
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
organism filter elapsed: 220.65s
depleted.solver set to gurobi
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=166)...
gap-fill done in 0.22s, added=0, failure_mode=infeasible: gap filling optimization failed (infeasible).
metrics: recall=0.000, precision=n/a, jaccard=0.000, growth_ratio=-0.000, overhead=-3, elapsed=226.95s
```
