# Run notes — e_coli_core v7 (overlay on auto-generated)

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
  metabolite-compat filter: SKIPPED (v7 default)
organism filter elapsed: 120.55s
depleted.solver set to gurobi
running cobra.flux_analysis.gapfilling.gapfill(lower_bound=0.05, universal_size=22754)...
gap-fill done in 245.77s, added=2, failure_mode=ok
metrics: recall=0.000, precision=0.0, jaccard=0.000, growth_ratio=5.509, overhead=-1, elapsed=381.99s
```

---

## Re-evaluation under design.md §2 metric framework

**This is the first run in the v2-v7 series that exits `failure_mode: "ok"`.**
The pipeline change that did it: turning off the metabolite-compat filter
(v7 default per supervisor 2026-05-18).

### Functional family

| Metric | Value | Note |
|---|---:|---|
| `baseline_growth` | 0.873922 | wild-type |
| `depleted_growth` | 0.000000 | `ENO` + `ACONTa` + `ICL` removed |
| `gapfilled_growth` | **4.814289** | ~5.5× baseline (red flag) |
| `growth_recovery_ratio` | **5.5088** | non-physical |
| `growth_diff` | 3.940 | |
| `n_added_reactions` | 2 | minimal gap-fill |
| `reaction_overhead` | -1 (added 2, removed 3) | |
| `over_addition` | 2 | (both added reactions are outside removed set) |
| `failure_mode` | `ok` | cobrapy validation passed |

### Benchmark family

| Metric | Value | Note |
|---|---:|---|
| `recovery_recall` | 0.000 | 0/3 of removed reactions restored |
| `recovery_precision` | 0.000 | 0/2 of added reactions match removed |
| `reaction_id_jaccard` | 0.000 | |

### Interpretation

`gapfilled_growth = 4.81` against `baseline = 0.87` is biologically
impossible (~5.5× wild-type biomass yield). Gurobi exploited the
reversibility correction to discover an energy-generating cycle or
similarly non-physical flux loop. cobrapy validated it as "OK" because
its validate step only checks `growth >= lower_bound` — there is no
thermodynamic sanity check.

This is exactly the case that `AGENTS.md §Goal §Implication for
evaluation` flagged when adopting the reversibility correction:

> non-physical flux (EGC etc.) is caught downstream by Q1/Q2 quality
> tests

Q1/Q2 task suites are not yet implemented (`design.md §5 Phase 1
step 4`). Once they are, this run's "ok" would be re-labeled.

### Pipeline accounting

- `organism_filter_time_sec`: 120.55 (cobra `universal.copy()` + KEGG
  no-op + remove non-organism)
- `gapfill_time_sec`: 245.77 (Gurobi MILP at 22,754 candidates;
  vs v4's 0.22 s at 166 candidates — ~1100× slower, expected for
  generic MIP scaling)
- `elapsed_sec`: 381.99 (≈ 6.4 min, well under the 15-min cap)

### Cross-references

- Pre-v7 e_coli_core runs (v2/v3/v4/v5) all hit `infeasible` in <1 s
  because the metabolite-compat filter shrunk candidates to 166 with
  no viable alternative pathway. See
  `experiments/gapfilling/20260513_smoke_v2_5pct_eco_core/notes.md`
  through `20260514_smoke_v3_5pct_eco_core/notes.md`.
- v6 diagnosis that pointed at the filter:
  `experiments/audit/20260517_filter_diagnosis/notes.md`.
- The reversibility-correction decision that enabled this loop:
  `experiments/audit/20260514_gapfill_diagnosis/notes.md` plus
  supervisor 2026-05-14.
