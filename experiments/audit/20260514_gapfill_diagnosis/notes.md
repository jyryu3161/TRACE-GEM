# Gap-fill recall=0 diagnosis — iML1515 / 5% / seed 42

**Date**: 2026-05-11
**Trigger**: `experiments/gapfilling/20260513_smoke_v2_5pct_eco_iML1515`
reported `recovery_recall: 0.0`, `failure_mode: infeasible` despite the
universe filter shrinking the BiGG universal to 4664 reactions and
gap-fill returning in 8 s. The 113 removed reactions were verified to be
present in the universal (Step 1 / line 79 of `step1_log.txt`).

## Root cause (one line)

**The BiGG universal model stores 32.7% of iML1515's reversible reactions
as forward-only `(0, 1000)`. cobrapy's `gapfill()` adds reactions FROM
the universal WITH those bounds, so the restored model is missing the
essential reverse fluxes — biomass becomes infeasible.**

## Evidence

### Step 1 — manual restore from universal does *not* recover growth

`diagnose.py` reproduces recovery_runner's exact sampling, then bypasses
the cobrapy MILP and directly `add_reactions(universal.reactions[rid])`
for every removed reaction. Result (`step1_summary.json`):

```json
{
  "baseline_growth": 0.876997,
  "depleted_growth": 0.0,
  "restored_growth": 0.0,
  "n_removed": 113,
  "n_found_in_universal": 113,
  "metabolites_orphan_removed": 13
}
```

- Every removed reaction exists in the universal → ID match is not the
  bottleneck.
- Manual restore yields **growth = 0**, same as depleted → it is *not*
  cobrapy's MILP search that fails. The candidate set itself cannot
  rescue biomass.

First-5 inspection (excerpt from `step1_log.txt`):

```
--- CBMKr ---
    orig bounds: (-1000.0, 1000.0)    universal bounds: (0.0, 1000.0)    match=False
    orig reaction: atp_c + co2_c + nh4_c <=> adp_c + cbp_c + 2.0 h_c
    uni  reaction: atp_c + co2_c + nh4_c --> adp_c + cbp_c + 2.0 h_c
    metabolite-stoich match: True
```

Stoichiometry was identical for all 5 sampled. Bounds differed for 2 of 5.

### Step 2 — restore with original iML1515 bounds → full recovery

`diagnose_step2.py` runs the same restoration but **overrides each
universal reaction's bounds with iML1515's original bounds before
`add_reactions`**. Result (`step2_summary.json`):

```json
{
  "baseline_growth": 0.876997,
  "depleted_growth": 0.0,
  "restored_with_original_bounds_growth": 0.876997,
  "restored_with_universal_bounds_growth": 0.0,
  "n_bound_mismatches": 37,
  "n_stoich_mismatches": 0,
  "bound_mismatch_classes": {
    "reversible_to_forward": 37,
    "forward_to_reversible": 0,
    "other": 0
  }
}
```

- 37 / 113 reactions (32.7 %) have bounds mismatches.
- **All 37 are the same pattern**: iML1515 reversible `(-1000, 1000)`
  → universal forward-only `(0, 1000)`. Zero stoichiometry differences.
- With original bounds, growth = 0.876997 = `1.0000 × baseline` →
  the cobrapy solver finds these reactions perfectly well when their
  reversibility is intact.

First 10 affected reactions:

```
CBMKr        [-1000.0, 1000.0] -> [0.0, 1000.0]
GLCATr       [-1000.0, 1000.0] -> [0.0, 1000.0]
CYNTtex      [-1000.0, 1000.0] -> [0.0, 1000.0]
ATHRDHr      [-1000.0, 1000.0] -> [0.0, 1000.0]
5DGLCNt2rpp  [-1000.0, 1000.0] -> [0.0, 1000.0]
4HOXPACDtex  [-1000.0, 1000.0] -> [0.0, 1000.0]
ARGSL        [-1000.0, 1000.0] -> [0.0, 1000.0]
FRULYSDG     [-1000.0, 1000.0] -> [0.0, 1000.0]
SUCOAS       [-1000.0, 1000.0] -> [0.0, 1000.0]
URItex       [-1000.0, 1000.0] -> [0.0, 1000.0]
```

Several of these (e.g. `SUCOAS` = Succinyl-CoA synthetase, `ARGSL` =
Argininosuccinate lyase) are well-known reversible reactions in central
metabolism. Forcing them forward-only blocks biosynthetic pathways.

## Why this defeats `cobra.flux_analysis.gapfilling.gapfill()`

cobrapy's gap-fill builds a MILP over candidate reactions exactly as they
appear in the donor model (universal). Quote from cobra 0.30.0 source
behavior — `gapfilling.gapfill()` uses each universal reaction's
`lower_bound` and `upper_bound` directly when constructing the LP. There
is no automatic reversibility relaxation. If the donor's bounds make the
target infeasible, the MILP returns infeasible regardless of how many
reactions are available to add.

This is *not* a recovery_runner bug. It is a property of the BiGG
universal model file (`data/bigg_universal_model_fixed.json`) being used
as the donor pool.

## Recommended response

In order of effort:

### A. Relax universal bounds before gap-fill (1-line fix, recommended)

After loading the universal in `recovery_runner.py`, force every reaction
to reversible: `rxn.lower_bound = -1000.0` for all `rxn` whose
`upper_bound > 0`. cobrapy's gap-fill will then minimise reactions added
without the artificial directional constraint. Whether the *final*
restored bounds should mirror iML1515 or the universal is a separate
decision (see `B`).

This requires changing **recovery_runner.py only** (no `src/` ripple).

### B. Restore reactions with original-model bounds, not universal bounds

Even after gap-fill picks reactions, recovery_runner could look up each
chosen reaction's bounds in the *original* model (when available) and
override the universal bounds with those. This makes `recovery_recall`
measure "reaction identity recovery" rather than "reaction-plus-bounds
recovery", which is closer to the AGENTS.md protocol's intent
(`§Gap-filling protocol: Recovery recall — fraction of removed reactions
restored`).

### C. Use a different donor model

The `data/bigg_universal_model_fixed.json` file is a "fixed" version
likely processed for some specific compatibility purpose. A donor that
preserves reversibility (e.g. one built directly from iML1515 + its
sibling models) would not have this issue, but creating it is a larger
task.

### D. Out of scope for now — KEGG `OrganismFilter` repair

Unrelated to this diagnosis. KEGG `/link/reaction/<organism>` returns
HTTP 400 as of 2026-05-11 (see
`experiments/gapfilling/20260513_smoke_v2_summary.md §Known issue`).
Independent of the bounds problem.

## Suggestion for the meeting

Choose A (or A+B). Both are small edits to `recovery_runner.py`. After
that, re-run the 5%/seed42 case and confirm `recovery_recall > 0` before
launching the full 5/10/15% × 5-seed sweep.

## Files written by this audit

```
experiments/audit/20260514_gapfill_diagnosis/
├── diagnose.py            (Step 1 probe)
├── step1_log.txt          (Step 1 full output)
├── step1_summary.json     (Step 1 metrics)
├── diagnose_step2.py      (Step 2 probe)
├── step2_log.txt          (Step 2 full output)
├── step2_summary.json     (Step 2 metrics)
└── notes.md               (this file)
```

Time spent: ~25 min (Step 1 ~10 min, Step 2 ~10 min, write-up ~5 min).
Within the 60-min cap.

---

## Tool's existing bound handling

Question for this section: does the *tool itself* (UniversalLoader,
OrganismFilter, GapFillEngine) preprocess universal bounds before passing
them to cobrapy's `gapfill()`? If yes, recovery_runner bypassed that
preprocessing and the fix is "do the same thing". If no, the tool has
the same latent issue — Prof. Ryu's pipeline never tripped on it because
its task-driven flow exercises different reaction subsets.

**Result: no bound preprocessing anywhere in the pipeline.** Verified by
grep across `src/core/universal_loader.py`, `src/core/cobra_utils.py`,
`src/gapfill/organism_filter.py`, `src/gapfill/engine.py`,
`src/gapfill/penalty_calculator.py`, `src/gapfill/gpr_assigner.py`.

### 1. `UniversalLoader` — zero bound code

```
$ grep -nE 'lower_bound|upper_bound|bounds|reversible' src/core/universal_loader.py
(no matches)
```

`load_json()` and `load_sbml()` (universal_loader.py:42-72) call
`cobra.io.load_json_model()` / `read_sbml_model()` and return the result.
The universal is consumed with whatever bounds the donor JSON file has.

### 2. `extract_candidates` → `convert_cobra_reaction` — read-only

`src/core/cobra_utils.py:32-34`:

```python
return Reaction(
    ...
    lower_bound=rxn.lower_bound,
    upper_bound=rxn.upper_bound,
    ...
)
```

Bounds are **read** into the internal `Reaction` dataclass (used for
scoring / display). The original `cobra.Reaction` objects that gap-fill
operates on are unchanged.

### 3. `OrganismFilter.filter_candidates()` — zero bound code

```
$ grep -nE 'lower_bound|upper_bound|bounds|reversible' src/gapfill/organism_filter.py
(no matches)
```

`filter_candidates()` (organism_filter.py:76-118) only assigns
`candidate.organism_exists` and `candidate.kegg_organism_genes`. The
underlying `cobra.Reaction` objects are not copied or modified.

### 4. `GapFillEngine._gapfill_for_task()` — modifies user model, NOT universal

`src/gapfill/engine.py:348-413`:

```python
test_model = model.copy()                # <-- USER model copy
# Apply task medium: close all exchanges, then open specified ones
for rxn in test_model.reactions:
    if rxn.id.startswith("EX_"):
        rxn.lower_bound = 0.0            # USER model
for rxn_id, lb in task.medium.items():
    rxn.lower_bound = lb                 # USER model
for rxn_id, (lb, ub) in task.constraints.items():
    rxn.lower_bound = lb                 # USER model
    rxn.upper_bound = ub                 # USER model
...
result = cobra.flux_analysis.gapfilling.gapfill(
    test_model,
    universal,                           # <-- passed AS-IS, no preprocessing
    lower_bound=lower_bound,
    penalties=penalties,
)
```

All bound edits are on `test_model` (the user model copy) for medium /
task constraints / demand-reaction setup. The `universal` argument is
forwarded unchanged.

### Verdict

The tool does **not** relax universal bounds. recovery_runner.py did
not bypass anything; both paths feed cobrapy `gapfill()` the same
unmodified donor. The bound-mismatch failure mode therefore applies to
the entire pipeline — it just hasn't surfaced in the task-driven flow
that Prof. Ryu's tool exercises, presumably because:

- The task-driven flow gap-fills only for *failed* metabolic tasks; the
  needed candidate subset typically does not require reverse fluxes that
  universal forces forward.
- The organism filter (when KEGG worked) reduced the candidate pool
  further, lowering the chance of bound-driven infeasibility.
- A fallback to `lower_bound=0.01` exists (engine.py:323).

For the **GPR-removal recovery protocol**, where removed reactions are
chosen blindly across the whole GPR-positive set including reversible
ones, the issue surfaces immediately. Fix options A/B from §Recommended
response apply.

If Prof. Ryu agrees that universal bounds should be relaxed pre-gap-fill
in general, a small patch to `src/gapfill/engine.py` (one loop relaxing
`universal.reactions[*].lower_bound = -1000` for `upper_bound > 0`)
would benefit the entire tool, not just `recovery_runner.py`. That patch
is out of scope for this audit but is the natural follow-up if the
diagnosis is accepted.
