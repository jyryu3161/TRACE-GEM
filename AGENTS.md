# Agent Guide

This repository is a genome-scale metabolic model evidence evaluator and
task-aware gap-filling platform. Agents working here should keep changes
scoped, preserve model/version integrity, and avoid reintroducing inactive
evidence sources.

## Quick Commands

```bash
python -m src.app
metatask-gapfill
python -m src.cli --help
metatask-gapfill-cli --help
pytest
ruff check src/ tests/
ruff format src/ tests/
mypy src/ --ignore-missing-imports
```

## Active Product Scope

- Evidence is KEGG and BiGG only.
- PubMed, Gemini, Perplexity, UniProt, MetaCyc, and LLM evidence workflows are
  intentionally removed from active code and tests.
- KEGG and BiGG confidence scores use fixed configured weights. Missing/absent KEGG
  evidence must not be redistributed into a 1.0 BiGG-only score.
- KEGG entries with metabolite mismatches should be reported as explicit absent
  KEGG evidence with mismatch details, not as generic "not found".
- KEGG substrate/product matching excludes common currency metabolites when
  informative non-currency compounds remain on both sides.
- Default candidate evidence evaluation is eager for all candidates:
  `Config.candidate_evidence_eager_limit = 0`.
- Deferred evidence mode is still available by setting
  `candidate_evidence_eager_limit` to a positive threshold. In that mode, large
  candidate sets skip full pre-gap-fill evidence and evaluate only gap-filled
  reactions.
- CLI gap-fill mode takes a draft model, universal model, metabolic task CSV,
  and optional `--medium`. If medium is omitted, use the draft COBRA model's
  default medium; otherwise accept JSON, CSV/TSV, or inline specs like
  `glc__D_e(-10);o2_e(-1000)`.

## Gap-Filling Behavior

- Gap-fill is driven by metabolic tasks from
  `data/universal_essential_tasks.csv`.
- `TaskRunner.prepare_task_model()` is the shared source of truth for task
  environment setup. It handles task medium, free exchanges, trace elements,
  cofactor turnover, constraints, and ID normalization.
- `GapFillEngine` must use the same task environment as task evaluation.
- Only lower-bound production tasks (`>` and `>=`) are gap-fillable. Negative,
  equality, and upper-bound tasks cannot generally be fixed by adding reactions.
- Previously passing tasks are protected during gap-fill. Candidate reaction
  sets that regress those tasks should be discarded, and applied iterations
  that still cause regressions should be rolled back.
- `Config.gapfill_iterations` controls the outer repair/retest convergence loop.
  It does not enumerate multiple alternative reaction sets.
- `Config.gapfill_alternatives` controls how many COBRApy alternative solution
  sets are tried per failed task. If an alternative breaks a protected task,
  try the next alternative; if none preserve protected tasks, that task's
  gap-fill attempt is infeasible.
- Large universals are pruned for MILP solving above
  `Config.gapfill_universal_prune_threshold`, keeping model-compatible
  reactions and explicit task targets.

## Important Files

```text
src/api/                 KEGG/BiGG clients, rate limiting, circuit breaker
src/core/models.py       Domain dataclasses
src/core/task_parser.py  TaskParser and TaskRunner
src/core/universal_loader.py
src/evidence/engine.py   KEGG/BiGG evidence orchestration
src/evidence/scoring.py
src/gapfill/engine.py    Task-aware gap-fill workflow
src/gapfill/organism_filter.py
src/gapfill/penalty_calculator.py
src/gui/workers.py       GUI background workflow execution
src/gui/controllers/     GUI controller layer
src/versioning/          Model version snapshots, diffs, storage
src/utils/config.py      Runtime defaults
```

## Data Files

```text
data/iML1515.xml
data/bigg_universal_model_fixed.json
data/universal_essential_tasks.csv
```

Optional local mapping files improve evidence quality when present:

```text
data/reac_xref.tsv
data/reaction_analysis_result.tsv
data/bigg_models_reactions.txt
data/bigg_models_metabolites.txt
```

## Engineering Rules

- Use COBRApy structures for actual model math. Keep GUI/domain models in sync
  via `src/core/cobra_utils.py`.
- Copy reactions before adding universal reactions to a user model.
- Preserve version history for user-visible model edits.
- Restore versions should store `restore_source_version_id` so the graph can
  render restore branches from the restored source instead of inferring from
  descriptions only.
- Keep async API work out of the GUI thread; use GUI workers.
- Mock external APIs in tests.
- Do not stage unrelated local files. The untracked diagnostic report
  `docs/gapfill-task-debug-report.md` may be present locally and is not part of
  normal commits unless explicitly requested.

## Test Focus For Changes

- Evidence changes: `tests/test_evidence_engine.py`, `tests/test_scoring.py`,
  `tests/test_kegg_client.py`, `tests/test_bigg_client.py`.
- Gap-fill changes: `tests/test_gapfill_engine.py`,
  `tests/test_integration_gapfill.py`, `tests/test_gui_workers.py`.
- Versioning changes: `tests/test_version_manager.py`,
  `tests/test_diff_engine.py`, `tests/test_project_manager.py`.
- GUI changes: relevant `tests/test_gui_*` modules plus offscreen smoke tests
  where possible.
