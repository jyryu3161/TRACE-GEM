# Run notes

```
recovery_runner v4: model=data/iML1515.xml ratio=0.05 seed=42 organism=eco solver=gurobi (v12.0.3)
loading user model...
  user model: 2712 rxns, 1877 mets
loading universal model via UniversalLoader...
  universal: 28301 rxns, 15638 mets
  reversibility correction: lower_bound -> -1000 on 28301 universal reactions
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
organism filter elapsed: 185.21s
depleted.solver set to gurobi
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=4664)...
gap-fill done in 11.57s, added=0, failure_mode=error: RuntimeError: Failed to validate gap filled model, try lowering the integer threshold.
metrics: recall=0.000, precision=n/a, jaccard=0.000, growth_ratio=0.000, overhead=-113, elapsed=207.33s
```
