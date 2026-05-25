# Prior art review — gap-filling-platform infrastructure (Prof. Jaeyong Ryu)

**Date**: 2026-05-26
**Trigger**: Phase 1.3 (bkit integration) discovered that `docs/01-04*/features/`
already contains 8 PDCA documents from a 2026-02-21 cycle authored by
Prof. Jaeyong Ryu. Reviewing before starting our own `q1-test-egc`
PDCA cycle to (a) avoid duplicate work, (b) identify reusable scaffolding,
(c) confirm our diagnoses (v4–v7) are genuinely novel.

## Verdict

Prof. Ryu's 2026-02-21 cycle built the **production gap-fill platform
infrastructure** — universal model loading, task-driven workflow,
candidate filtering, GUI/CLI wiring. **Match Rate 97%** (36/37 design
items implemented; only `tests/test_gui_task_panel.py` missing). His
work is task-driven (run metabolic tasks before/after gap-fill, score
candidates by evidence). Our auto-research branch's v4–v7 work is a
parallel, separate codepath (`src/gapfill/recovery_runner.py` — random
GPR removal benchmark) that bypasses the production engine. The two
codebases share the universal model file (`data/bigg_universal_model_fixed.json`)
and the lower-bound default (`0.05`) but otherwise do not overlap.

## Files reviewed

| File | Lines | Role |
|---|---:|---|
| `docs/03-analysis/features/gap-filling-platform.analysis.md` | 196 | Full read |
| `docs/03-analysis/features/stability-scoring-versioning.analysis.md` | 126 | Full read |
| `docs/02-design/features/gap-filling-platform.design.md` | 1,079 | Headers only + keyword grep |
| `docs/01-plan/features/*.plan.md`, `docs/04-report/features/*.report.md` | — | Author + date verified via `git log` only |

## Findings

### 1. Production infrastructure that exists (reusable)

| Module | Location | Q1-test relevance |
|---|---|---|
| `GapFillEngine` (5-phase pipeline) | `src/gapfill/engine.py` | **High** — `_run_tasks(phase="before"/"after")` is the exact scaffold we need to register Q1 as a task |
| `TaskParser` + `TaskRunner` | `src/core/task_parser.py` | **High** — parses `data/universal_essential_tasks.csv`; supports `>`, `<`, `=`, `>=`, `<=` operators |
| `MetabolicTask` / `TaskResult` dataclasses | `src/core/models.py` | **High** — extensible; Q1 EGC catch fits as a magnitude-bound task |
| `UniversalLoader` | `src/core/universal_loader.py` | Medium — already handles the universal model we use |
| `OrganismFilter` | `src/gapfill/organism_filter.py` | Medium — KEGG-organism filtering; not central to Q1 but available |
| `PenaltyCalculator` | `src/gapfill/penalty_calculator.py` | Low — evidence-score-based penalty; tangential to EGC detection |
| `GPRAssigner` | `src/gapfill/gpr_assigner.py` | Low |
| GUI (`workflow_wizard`, `candidate_table`, `task_panel`, `gapfill_panel`) | `src/gui/` | None — Q1 is a programmatic check, not a UI feature |
| Version control (`src/versioning/*`) | from stability-scoring-versioning cycle | None |

### 2. Mapping to our v4–v7 work

| Our work | Prof. Ryu's infra | Note |
|---|---|---|
| `recovery_runner.py` (random-sampling benchmark) | `engine.py` (task-driven production) | **Different entry points** to the same universal model. v4–v7 bypassed the production engine entirely. |
| BiGG bound mismatch (v2/v3 infeasibility) | Same `bigg_universal_model_fixed.json` consumed | Production engine likely also affected; not verified in prior art |
| metabolite-compat filter (v6 diagnosis) | Not present in prior art | Our addition in v4–v7; production engine uses `OrganismFilter` instead |
| EGC 5.5× growth (v7 e_coli_core) | Production has no thermodynamic check | cobrapy's `validate()` is the only validator on both paths → production would also pass 5.5× as "ok" |
| 2×2 framework (Q1–Q4 in AGENTS.md) | Not present | See §4 below |
| Reference-free policy (AGENTS.md §Goal) | Implicit (KEGG/BiGG only) but never named | Aligned in spirit |

### 3. Q1 test reusability path (recommended scaffold)

The cheapest correct integration:

1. Add a new row to `data/universal_essential_tasks.csv` for the Q1 EGC check
   (something like: `task_id=q1_egc, task_type=biomass, expected_operator=<=,
   expected_value=<N>×baseline`).
2. Extend `MetabolicTask` / `TaskRunner` only if the current operator set
   can't express the bound (it probably can — `<=` is already supported per
   the analysis report Section 1.1 item 13).
3. Q1 then runs automatically as part of `_run_tasks(phase="after")` for
   any gap-fill workflow (production engine OR a recovery_runner that
   calls into engine).

No new module needed if we go this route. Open question (q1) below decides
whether v4–v7's `recovery_runner` plugs into this scaffold or stays
separate.

### 4. Keyword search — our contribution remains novel

Searched all 8 prior-art files for terms tied to our diagnoses:

```
grep -ni "EGC|thermodynam|energy generating|Q1|Q2|Q3|Q4|atp.yield" \
  docs/01-plan/features/*.md docs/02-design/features/*.md \
  docs/03-analysis/features/*.md docs/04-report/features/*.md
```

**Result: 0 matches** (only false positives on "PDCA cycle" strings).

Our work therefore introduces genuinely new content:

- **EGC detection as a quality criterion** (v7 finding, not in prior art)
- **2×2 task quality framework** (AGENTS.md §Task quality, not in prior art)
- **Reference-free as an explicit policy** (AGENTS.md §Goal — Prof. Ryu's
  code happens to be reference-free but the policy is not stated)
- **BiGG universal bound mismatch diagnosis** (v2/v3, not in prior art)
- **Metabolite-compat filter root-cause analysis** (v6, not in prior art —
  prior art does not use such a filter)

These belong to us and should be carried forward as the Q1 PDCA's
starting facts.

## Future contribution opportunity (not now)

Prof. Ryu's gap analysis report flags one unresolved item:

> **MISSING**: `tests/test_gui_task_panel.py` — design lists this file but
> it does not exist. (`gap-filling-platform.analysis.md` line 149.)

Adding this file would close his cycle's only open gap. **Not in scope
for Phase 1.3 or the upcoming Q1 cycle.** Flagging here so it isn't
forgotten — could be a small good-faith contribution once Q1 work is
underway and we touch the GUI test infrastructure for other reasons.

## Open questions

### q1 — Q1 test integration path

Two viable approaches:

- **Option X** — Add Q1 check inline in `recovery_runner.py` after each
  gap-fill, before reporting `failure_mode`. Keeps the auto-research
  benchmark codepath self-contained. v7_retry_notes.md §Suggested next
  steps already pointed at this. Faster to ship; isolates our research
  from production behavior.
- **Option Y** — Register Q1 as a `MetabolicTask` row in
  `data/universal_essential_tasks.csv` and let
  `GapFillEngine._run_tasks(phase="after")` execute it. Both the
  production engine and (if `recovery_runner` calls into engine.py)
  the benchmark codepath get the check for free. Higher leverage;
  requires `recovery_runner` to consume the task framework.

**Decision pending** — user/PI call.

### q2 — Coordination with Prof. Ryu

Two options:

- **Tell him now** that we reviewed his PDCA artifacts as prior art,
  surface our intent to extend `MetabolicTask` for Q1, and ask if he
  wants to coordinate.
- **Wait** for the next regular meeting and bring it up naturally with
  the Q1 results in hand (so the discussion is concrete, not speculative).

**Decision pending** — user call. Recommend mentioning before any code
that touches `src/gapfill/engine.py` or `data/universal_essential_tasks.csv`,
to avoid stepping on his production work without warning.

## Files

```
experiments/audit/20260526_prior_art_review/
└── notes.md   (this file)
```

No script artifact for this audit — pure document review.

## Time

- Reading the 2 analysis docs (196 + 126 lines): ~7 min
- Header scan + keyword grep on design.md: ~2 min
- Writeup: ~6 min
- **Total: ~15 min** (within 30-min Phase 1.3e cap)
