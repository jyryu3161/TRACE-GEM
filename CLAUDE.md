# MetaTaskGapFill

Genome-scale metabolic model evidence evaluator and task-aware gap-filling
platform. The application loads SBML/COBRA models, evaluates reaction evidence
against KEGG and BiGG, checks metabolic tasks, repairs missing reactions with
COBRApy gap-filling, and tracks model versions.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Commands

```bash
# Run the app
python -m src.app
metatask-gapfill

# CLI
python -m src.cli --help
metatask-gapfill-cli --help

# Run tests
pytest
pytest tests/test_gapfill_engine.py tests/test_gui_workers.py

# Coverage
pytest tests/ --cov=src --cov-report=term-missing

# Lint and format
ruff check src/ tests/
ruff check src/ tests/ --fix
ruff format src/ tests/

# Type check
mypy src/ --ignore-missing-imports
```

## Current Scope

- Evidence sources are KEGG and BiGG only.
- PubMed, Gemini, Perplexity, UniProt, MetaCyc, and LLM-based evidence paths are
  intentionally not part of the active codebase.
- KEGG and BiGG confidence scores use their configured fixed weights. Do not
  redistribute a missing/absent source's weight into the remaining source; a
  BiGG match with absent KEGG evidence must not become confidence `1.0`.
- KEGG IDs whose entries exist but whose substrates/products do not match the
  model reaction should remain explicit absent KEGG evidence with mismatch
  details, not a generic "not found" result.
- Default candidate evidence behavior is eager: all extracted candidate
  reactions are evaluated before gap-filling. `Config.candidate_evidence_eager_limit`
  is `0` by default; set it to a positive threshold to defer evidence for large
  universals and evaluate only gap-filled reactions.
- CLI gap-fill mode accepts draft model, universal model, metabolic task CSV,
  and optional base medium. If `--medium` is omitted, use the draft COBRA
  model's default medium. If provided, medium may be JSON, CSV/TSV, or inline
  spec such as `glc__D_e(-10);o2_e(-1000)`.
- Gap-filling is metabolic-task-aware. Task evaluation and gap-fill setup share
  `TaskRunner.prepare_task_model()` so medium, free exchanges, trace elements,
  cofactor turnover, constraints, and ID normalization stay consistent.
- Negative or upper-bound tasks are not gap-fillable and are skipped by the
  reaction-addition repair step.
- Previously passing tasks are protected during gap-fill. Candidate sets that
  would break them are discarded, and an applied iteration is rolled back if
  final task retesting still shows protected-task regressions.
- The gap-fill workflow has an outer convergence loop controlled by
  `Config.gapfill_iterations`. This is not the same as alternative solution
  enumeration; each task currently keeps the first COBRApy gap-fill solution.
- Large universal models are pruned for MILP solving when above
  `Config.gapfill_universal_prune_threshold`, keeping reactions compatible with
  the draft model metabolite set plus explicit task targets.

## Project Structure

```text
src/
├── api/                 # Async external/local evidence clients
│   ├── base_client.py   # Rate limiting, retry, circuit breaker base class
│   ├── bigg_client.py   # BiGG API/local evidence checks
│   ├── bigg_lookup.py   # BiGG local lookup helpers
│   ├── kegg_client.py   # KEGG evidence checks
│   └── rate_limiter.py
├── cache/               # SQLite cache layer
│   ├── cache_manager.py
│   └── schema.py
├── core/                # Domain models and COBRA/SBML utilities
│   ├── cobra_utils.py
│   ├── gpr_parser.py
│   ├── id_mapper.py
│   ├── mapping_data.py
│   ├── models.py
│   ├── project_manager.py
│   ├── sbml_parser.py
│   ├── task_parser.py   # TaskParser and TaskRunner
│   └── universal_loader.py
├── evidence/            # KEGG/BiGG evidence orchestration and scoring
│   ├── engine.py
│   ├── evidence_types.py
│   └── scoring.py
├── gapfill/             # Task-aware gap-filling, penalties, GPR assignment
│   ├── engine.py
│   ├── gpr_assigner.py
│   ├── organism_filter.py
│   └── penalty_calculator.py
├── gui/                 # PySide6 GUI, panels, controllers, workers
│   ├── controllers/
│   ├── candidate_table.py
│   ├── gapfill_panel.py
│   ├── main_window.py
│   ├── reaction_removal_dialog.py
│   ├── score_visualization.py
│   ├── task_panel.py
│   ├── version_panel.py
│   ├── workers.py
│   └── workflow_wizard.py
├── utils/               # Config, constants, logging, subsystem loading
│   ├── config.py
│   ├── constants.py
│   ├── logging_config.py
│   └── subsystem_loader.py
├── versioning/          # Model snapshots, diffs, storage, summaries
│   ├── change_summarizer.py
│   ├── diff_engine.py
│   ├── storage.py
│   └── version_manager.py
└── app.py               # GUI entry point
```

## Data Files

- `data/iML1515.xml`: primary E. coli test model.
- `data/bigg_universal_model_fixed.json`: large BiGG universal model.
- `data/universal_essential_tasks.csv`: universal metabolic task set.
- Optional local mapping files, when present, improve evidence and organism
  filtering: `reac_xref.tsv`, `reaction_analysis_result.tsv`,
  `bigg_models_reactions.txt`, `bigg_models_metabolites.txt`.

## Implementation Notes

- Use COBRApy models as the authoritative model state when running tasks and
  gap-fill. Synchronize GUI/domain `ModelData` through `core.cobra_utils`.
- Keep API calls async and off the GUI thread. GUI workers create their own
  asyncio event loops.
- Do not add PubMed/Gemini/Perplexity evidence code back unless the product
  scope explicitly changes.
- For metabolic tasks, prefer reusing `TaskRunner` public/shared helpers over
  reimplementing environment setup in gap-fill code.
- When adding reactions from a universal model, copy COBRA reactions before
  inserting them into the user model.
- Preserve model version history when user-visible model edits occur.
- Restore versions store `restore_source_version_id`; graph rendering should use
  that source for restore branch layout while retaining chronological parent
  history.

## Testing

- pytest + pytest-asyncio are used; external API calls must be mocked.
- GUI tests use offscreen Qt probing via `tests/conftest.py`.
- Gap-fill changes should cover:
  - task pass/fail before and after repair,
  - rollback of no-progress iterations,
  - rollback of protected-task regressions,
  - negative/upper-bound task skipping,
  - reaction copy semantics,
  - large universal pruning,
  - GUI worker evidence evaluation mode.
