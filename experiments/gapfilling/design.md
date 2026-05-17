# Gap-filling experiment type — design.md

> Type-wide design document for `experiments/gapfilling/<YYYYMMDD>_*/`.
> Per `AGENTS.md §Experiment storage`, this file locks in the
> hypothesis, method, and metrics for every gap-filling experiment.
>
> Written **retroactively** on 2026-05-13 after v1/v2/v3 smoke runs
> already produced. Future experiments under this type are bound by
> this design unless a successor `design.md` (or a `design_v2.md` —
> see §Design changes) is written first.

---

## 1. Purpose

This experiment type measures **gap-filling capability** of the
evaluator against a GEM (genome-scale metabolic model). It is the
training/validation environment for the long-term goal stated in
`AGENTS.md §Goal §Final research target`: *reference-free* model
quality enhancement, where an agent autonomously selects reactions
from a universal DB without comparing against a ground-truth.

The protocol asks one question:

> Given a model with `n%` of its GPR-positive reactions removed at
> random, how well can the gap-fill procedure restore it?

"Restore" splits into two distinct senses:

- **Functional restoration** — does growth and task quality return?
  This is production-relevant and survives the transition to
  reference-free use.
- **Identity restoration** — were the *same* reactions added back?
  This is benchmark-only. It cannot exist in the production setting
  because there is no "original" to compare to.

Both are measured here, but `recovery_recall` and its kin are flagged
as *benchmark-only* per `AGENTS.md §Gap-filling protocol`.

---

## 2. Two metric families

Per `AGENTS.md §Goal §Implication for evaluation`, every experiment
under this type emits both families.

### 2.1 Functional quality (production-relevant)

These metrics make sense in production where no ground-truth exists.

| Metric | Definition | Source |
|---|---|---|
| `baseline_growth` | FBA objective on the unmodified user model | `model.optimize()` |
| `depleted_growth` | FBA objective after removing the sampled reactions | same on depleted copy |
| `gapfilled_growth` | FBA objective after applying gap-fill additions | same on restored copy |
| `growth_diff` | `abs(baseline_growth - gapfilled_growth)` | derived |
| **Q1 pass rate** | Universal feasibility (EGC, anaerobic OXPHOS, …) | `tests/universal/feasibility/` |
| **Q2 pass rate** | Universal magnitude (ATP yield ≤ 38/glc, mass/charge) | `tests/universal/magnitude/` |
| **Q3 pass rate** | Species-specific feasibility (negative tasks) | `tests/species/<org>/feasibility/` |
| **Q4 pass rate** | Species-specific magnitude (yield ranges) | `tests/species/<org>/magnitude/` |
| `n_added_reactions` | Reactions added by gap-fill (overhead, lower better) | `cobra_gapfill()[0]` |
| `over_addition` | Additions not in the removed set (benchmark-shaded; report as "additions not justified by an obvious removal") | derived |

Q1–Q4 tests are not all implemented yet (see §6). Once they are, every
gap-filling experiment must report all four pass rates.

### 2.2 Benchmark identity (development only)

Valid only when ground-truth — the removed-reaction set — is recorded.

| Metric | Definition |
|---|---|
| `recovery_recall` | `|removed ∩ added| / |removed|` |
| `recovery_precision` | `|removed ∩ added| / |added|` (added if non-zero) |
| `recovery_jaccard` | `|removed ∩ added| / |removed ∪ added|` |

These metrics are useful for debugging and for tuning hyperparameters
(weights, lower_bound, organism filter aggressiveness). They are NOT
the goal. Per `AGENTS.md §Gap-filling protocol`:

> **Selection logic must be reference-free.** Approaches that exploit
> ground-truth information ... are not acceptable — they don't transfer
> to the production setting.

Any experiment whose selection logic touches `removed_reaction_ids` is
out of compliance and must be rejected.

---

## 3. Standard protocol

### 3.1 Models

| Phase | Model | File | Use |
|---|---|---|---|
| Phase 1 | iML1515 (E. coli K-12 MG1655) | `data/iML1515.xml` | primary dev + parameter tuning |
| Phase 1 (smoke) | e_coli_core | `data/e_coli_core.xml` | sanity / fast iterate |
| Phase 2 | iMM904 (S. cerevisiae) | not yet present | held-out generalization check |

Phase 2 begins only after Phase 1 reaches a stable parameter set
(per `AGENTS.md §Phase plan`). Tuning on iMM904 during Phase 1 is
forbidden.

### 3.2 Removal

- **Target set**: every reaction whose `gene_reaction_rule` is non-empty.
- **Sampler**: `random.Random(seed).sample(sorted_by_id, n)`.
  Sorting by ID first makes the sample reproducible regardless of the
  SBML reader's reaction iteration order. Implementation:
  `src/gapfill/recovery_runner.py:select_gpr_reactions`.
- **Ratios**: 0.05, 0.10, 0.15. Each is sampled independently from the
  original (not nested).
- **Seeds**: 42, 43, 44, 45, 46. Five replicates per ratio per model
  → 15 runs per model per parameter setting.

### 3.3 Universal DB

- **File**: `data/bigg_universal_model_fixed.json` (BiGG universal,
  cobrapy-compatible JSON).
- **Reversibility correction** *(supervisor decision 2026-05-14)*:
  on load, for every universal reaction with `upper_bound > 0`,
  set `lower_bound = -1000.0`. BiGG universal stores many reversible
  reactions as forward-only; without this correction, ~32% of removed
  reversible reactions cannot be restored. Non-physical fluxes (EGC,
  etc.) that this enables are caught downstream by Q1/Q2.
  Background: `experiments/audit/20260514_gapfill_diagnosis/notes.md`.
- **Pre-filtering**: applied *to candidates*, not to the donor
  fundamentally. Order:
  1. `UniversalLoader.extract_candidates(universal, depleted)`
     yields reactions in universal NOT in depleted.
  2. `OrganismFilter.filter_candidates(candidates)` marks
     `organism_exists`. Currently a no-op due to upstream KEGG outage
     (see §6); kept in pipeline for when the API is restored.
  3. Metabolite-compatibility filter: keep only candidates whose
     metabolites all already exist in the depleted model. This is
     reference-free (uses only depleted metabolite IDs, never
     `removed_reaction_ids`).

### 3.4 Gap-fill call

- **Filler**: `cobra.flux_analysis.gapfilling.gapfill()` (cobrapy
  public API; already a declared dependency).
- **Lower bound**: `0.05` (matches `Config.gapfill_lower_bound`).
- **Iterations**: `1` (the only stable mode for cobra 0.30.x).
- **Solver**: GLPK (cobra default) for now. **Planned upgrade to
  Gurobi** once licensing is settled — see §6.

### 3.5 CLI invocation (canonical)

```
.venv/bin/python -u -m src.gapfill.recovery_runner \
    --model data/iML1515.xml \
    --ratio 0.05 --seed 42 --organism eco \
    --output experiments/gapfilling/YYYYMMDD_<slug>/
```

Optional flags:

- `--lower-bound <f>`: override the gap-fill lower bound (e.g. `0.01`
  to mirror `engine.py:323` fallback).
- `--no-reversible-correction`: reproduce v2 behaviour (universal kept
  forward-only). Use only for ablation studies.

---

## 4. Per-experiment output

Each experiment directory contains exactly three files (per
`AGENTS.md §Experiment storage`):

```
experiments/gapfilling/<YYYYMMDD>_<slug>/
├── config.json     # all inputs: model_path, universal_path, ratio,
│                   # seed, lower_bound, reversible_correction,
│                   # organism, output_dir. Sufficient to re-run.
├── metrics.json    # functional family + benchmark family +
│                   # diagnostic fields (filter time, gapfill time,
│                   # universal sizes before/after, etc.)
└── notes.md        # surprises, what changed since last run, what
                    # to try next. Free-form but kept terse.
```

Slug conventions:

- Smoke / sanity runs: `<date>_smoke_v<N>_<ratio>pct_<organism>_<model>`
- Full sweeps: `<date>_sweep_<ratio>pct_seed<S>_<model>`
- Ablations: `<date>_ablation_<flag>_<model>`

Files larger than 5 MB go to `.gitignore` with their disk path noted
in `notes.md` (per `AGENTS.md §Git conventions`).

---

## 5. Phase plan for this type

### Phase 1 — iML1515 only

1. Smoke (current): single (ratio, seed) confirmed end-to-end.
2. Full sweep: 5/10/15% × 5 seeds = 15 runs.
3. Parameter sweep: lower_bound ∈ {0.05, 0.01}, organism filter on/off,
   reversibility correction on/off (latter for ablation only).
4. Q1–Q4 task quality coupling: every run reports all four pass rates
   once tests/universal and tests/species are populated.

### Phase 2 — iMM904 added

Apply Phase 1's settled parameters to iMM904 unchanged. Re-tuning on
iMM904 invalidates the generalization check.

---

## 6. Known issues (with links)

### 6.1 BiGG universal bound mismatch — RESOLVED in v3

32.7% of removed reversible reactions in iML1515 are stored as
forward-only in the universal. cobrapy `gapfill()` honours universal
bounds, so the recovered model misses essential reverse fluxes.

- Diagnosis: `experiments/audit/20260514_gapfill_diagnosis/notes.md`
- Fix: §3.3 reversibility correction. Applied by
  `src/gapfill/recovery_runner.py:_apply_reversibility_correction`.
- Tool-wide: `src/gapfill/engine.py` has the same latent issue but is
  out of scope for this design (`§Tool's existing bound handling` in
  the audit notes).

### 6.2 GLPK timeout on full-reversible MILP — OPEN

After reversibility correction, the MILP variable freedom roughly
doubles. GLPK does not return within 30 min on iML1515 with default
settings, even though a feasible solution provably exists
(yesterday's Step-2 diagnostic confirmed 1.0000 × baseline recovery
with manual restoration).

- Symptom: `experiments/gapfilling/20260514_smoke_v3_5pct_eco_iML1515/INCOMPLETE.md`
- Planned response: switch to **Gurobi** once licensing is settled.
  Until then, ratios beyond 5% on iML1515 are expected to time out.
  Smoke runs on e_coli_core remain useful for plumbing validation.

### 6.3 Random samples cutting essential pathways → infeasible — OPEN

For small models (e_coli_core, 95 reactions, 69 GPR-positive), a 5%
sample (3 reactions) frequently lands on central-metabolism essentials
(`ENO`, `ACONTa`, `ICL` for seed=42). The depleted model has no
alternative biomass-producing pathway, and no choice of additions
from a finite universal can rescue it. This is a property of the
protocol, not a tool failure — reported as `failure_mode: infeasible`
with `n_added_reactions: 0`.

- Example: `experiments/gapfilling/20260513_smoke_v2_5pct_eco_core/metrics.json`
- Implication: infeasibility rate is itself a metric to track. Once we
  have enough seeds, report:
  - "Recoverable" rate = fraction of (model, ratio, seed) tuples where
    gap-fill returned ≥ 1 reaction
  - For recoverable tuples only: recall, growth_diff, over_addition.

### 6.4 KEGG `/link/reaction/<organism>` returns HTTP 400 — UPSTREAM

KEGG REST has deprecated the bulk endpoint. `OrganismFilter` loads 0
reactions and marks every candidate `organism_exists=None`. The
candidate pool stays at ~all 28k, and the metabolite-compatibility
filter does the actual shrinking.

- Confirmed direct: `GET https://rest.kegg.jp/link/reaction/eco` → HTTP 400.
- `/list/organism` works → KEGG REST is up, only this endpoint changed.
- Not blocking experiments because metabolite-compatibility filter
  is sufficient. Filed for future repair against a working endpoint.

---

## 7. Design changes

This document is the contract for the gap-filling experiment type.
Methodology changes (new metric, new sampler, new filter, solver
swap, ratio change) require:

1. Updating this `design.md` with rationale and an effective date.
2. Recording the change in the next experiment's `notes.md` so the
   discontinuity is visible at the run level.

Per `AGENTS.md §Tie-breakers`: documented > undocumented. Don't change
the protocol silently.

---

## 8. Cross-references

- `AGENTS.md §Goal` — research target
- `AGENTS.md §Gap-filling protocol` — protocol synopsis
- `AGENTS.md §Task quality 2×2` — Q1–Q4 definitions
- `AGENTS.md §Experiment storage` — directory layout rules
- `src/gapfill/recovery_runner.py` — the runner implementing this design
- `experiments/audit/20260514_gapfill_diagnosis/notes.md` — bound-mismatch root cause
- `experiments/gapfilling/20260514_smoke_v3_notes.md` — v2 vs v3 comparison
