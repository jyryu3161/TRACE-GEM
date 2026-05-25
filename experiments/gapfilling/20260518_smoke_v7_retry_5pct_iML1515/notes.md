# Run notes — iML1515 v7_retry (overlay on auto-generated)

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
  metabolite-compat filter: SKIPPED (v7 default)
organism filter elapsed: 46.77s
depleted.solver set to gurobi
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=23742)...
gap-fill done in 3500.99s, added=0, failure_mode=error: RuntimeError: Failed to validate gap filled model, try lowering the integer threshold.
metrics: recall=0.000, precision=n/a, jaccard=0.000, growth_ratio=0.000, overhead=-113, elapsed=3558.29s
```

---

## Re-evaluation under design.md §2 metric framework

**Status: completed naturally at 58.3 min**, but cobrapy validation
rejected the Gurobi solution. Same error as v4/v5 (Gurobi-with-filter).
The v7 filter removal did NOT fix the iML1515 case, even though it
did fix e_coli_core.

### Functional family

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.876997 | wild-type |
| `depleted_growth` | 0.000000 | 113/2266 GPR reactions removed |
| `gapfilled_growth` | 0.000000 | no reactions added; growth unchanged |
| `growth_recovery_ratio` | 0.000 | |
| `growth_diff` | 0.877 | full deficit |
| `n_added_reactions` | **0** | cobrapy validation rejected → empty solution |
| `reaction_overhead` | -113 | |
| `over_addition` | 0 | |
| `failure_mode` | `error: RuntimeError: Failed to validate gap filled model, try lowering the integer threshold.` | |

### Benchmark family

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | 0.000 | nothing added |
| `recovery_precision` | None | denominator zero |
| `reaction_id_jaccard` | 0.000 | |

### Pipeline accounting

- `organism_filter_time_sec`: 46.77
- `gapfill_time_sec`: **3500.99 (58.3 min)** ← bulk of the run
- `elapsed_sec`: 3558.29
- `n_candidate_reactions`: 23,742 (vs 4664 in v4/v5)

## What this tells us

Gurobi *did* finish the MILP — it ran 58 minutes and returned an
"optimal" solution. The error is **post-MILP**: cobrapy's
`GapFiller.validate()` adds the chosen reactions to the original model
and re-optimises. If `objective < lower_bound` after that, it raises
`RuntimeError`.

So Gurobi picked a set of reactions, but when cobra actually built the
model with those additions, growth came out below 0.05. Possible
causes:

1. **MILP found a thermodynamic shortcut that disappears on validate.**
   Inside the MILP, the universal+depleted system has the relaxed
   bounds (reversibility correction) and the additions can use any
   metabolite. In `validate()`, cobra calls `original_model.copy()`
   and re-adds reactions. The original model's exchange and demand
   reactions enforce real biology, and the shortcut goes away.
2. **Gurobi solution is at the margin of feasibility.** With
   `lower_bound=0.05` and `integer_threshold=1e-9`, the MILP could be
   selecting a set where post-solve growth is 0.0499... vs 0.05. The
   numerical gap closes on the validation re-solve.
3. **Wrong cost minimisation target.** GapFiller's default penalty is
   1 per reaction, so MILP minimises `n_added`. If the *cheapest*
   answer doesn't actually work but a `n_added = 50` answer would,
   Gurobi has no reason to find the larger answer.

### Comparison to e_coli_core v7 (which DID succeed)

e_coli_core's MILP also found a "cheap" solution (n_added=2), but
because the original e_coli_core model is so small, even that cheap
solution opened a flux loop yielding `gapfilled_growth = 4.81`
(5.5× baseline). validation passed because growth > 0.05.

iML1515 has more biochemistry; the same "cheap" trick may not work,
or the trick disappears under the larger model's constraints. So
e_coli_core succeeds with a non-physical answer; iML1515 fails with
no answer.

Both are wrong, in different ways. Neither produces a recoverable
gap-fill in this seed.

## Suggested next steps

Listed in order of cheapest first:

### v8.A — pass Gurobi solver parameters via GapFiller(**kwargs)

cobrapy's `GapFiller(...)` forwards `**kwargs` to optlang. We can try:

```python
gapfiller = GapFiller(
    depleted, universal=target_universal,
    lower_bound=cfg.lower_bound,
    integer_threshold=cfg.integer_threshold,
    demand_reactions=True, exchange_reactions=False,
    mip_focus=2,         # seek proven optimal (vs default = balance)
    integrality_focus=1, # tighter near-integer detection
)
```

This may force Gurobi to find a more-integer-clean solution that
survives validation. Not guaranteed; this is solver tuning.

### v8.B — raise `lower_bound` margin

Set `--lower-bound 0.10` (or even `0.50`) to force the MILP toward
solutions with biomass solidly above the integer-threshold margin.
The Step-2 audit verified `growth = 0.877` is reachable with the
original 113 reactions, so any higher lower_bound up to ~0.4 should
still have a feasible solution available.

### v8.C — debug the chosen reactions

Instrument the runner to capture what Gurobi *would have* picked
before validation rejected it. Compare to the audit's known-feasible
manual set. This reveals whether the MILP is finding the right
reactions but failing at the integer cliff, or finding wrong reactions
entirely.

### v8.D — narrow universal further

Counter-intuitive given v7's whole point, but: now that we know v7
unfiltered runs to completion in ~1 h on iML1515, we can experiment
with a *less aggressive* filter than the metabolite-compat one v6
diagnosed as bad. For example, drop reactions that involve metabolites
absent from BOTH iML1515 and BiGG-core (≈ purely speculative
biochemistry). Smaller pool → faster MILP → better integer behaviour.

## Time accounting (v7_retry)

- Started: 17:44:30
- Completed naturally: ~18:43 (per file mtime), elapsed 58.3 min
- 60-min cap was not hit; this is a real result, not a timeout.

## Cross-references

- v6 diagnosis (which justified turning off the filter):
  `experiments/audit/20260517_filter_diagnosis/notes.md`
- v7 e_coli_core (which DID succeed with non-physical growth):
  `experiments/gapfilling/20260518_smoke_v7_eco_core/notes.md`
- Prior v4/v5 with same validation error but smaller pool:
  `experiments/gapfilling/20260517_smoke_v4_5pct_eco_iML1515/`,
  `experiments/gapfilling/20260517_smoke_v5_5pct_eco_iML1515/`
