# MetaTaskGapFill

Genome-scale metabolic model build + task-aware gap-filling platform. The
application builds draft models (CarveMe), checks metabolic tasks, and repairs
missing reactions with COBRApy gap-filling. During gap-filling, universal
candidate reactions are weighted by **KEGG evidence** (KEGG-only) so the
gap-filler prefers well-identified reactions. **Model quality is judged by
metabolic tasks, not by per-reaction evidence** — there is no standalone
"evaluate the whole model" feature. Model versions are tracked.

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

- **Evidence is KEGG-only and computed ONLY for gap-fill candidates** (universal
  reactions being considered for addition). It weights candidate penalties; it is
  not a model-quality signal. There is NO per-reaction model-evaluation feature —
  do not re-add one. PubMed, Gemini, Perplexity, UniProt, MetaCyc, LLM, and BiGG
  are intentionally NOT evidence sources.
- BiGG's only role is the **KEGG↔BiGG reaction mapping** used to source/identify
  gap-fill candidates (`MappingData.rxn_bigg_to_kegg`); it never contributes to
  the evidence tier.
- Tiers are **rule-based and threshold-free**, decided from three KEGG signals
  (in `evidence/scoring.py` `_classify_tier`): `kegg_anchored` (a KEGG reaction
  entry was retrieved), metabolite `reconciliation_state`
  (full/partial/none_contradictory/unverifiable — currency-filtered set equality,
  best-of-both-orientations), and `ec_concordance_state`
  (concordant/discordant/unknown). Four tiers: **High / Moderate / Low /
  Not-assessable** (Not-assessable = no KEGG anchor, distinct from Low). No
  continuous cutoffs (`0.2/0.5/0.8` etc. were removed).
- Conservative by construction (false positives are the priority for model
  extension): metabolite contradiction → always Low; EC discordance never yields
  High; `unverifiable + unknown EC` → Low; a KEGG ID rejected as a mismatch does
  not count as verified (`verified_kegg_reaction_ids`) and does not dodge the
  no-KEGG penalty.
- Candidate metabolites resolve to KEGG via `MappingData.met_bigg_to_kegg`
  (`id_mapper.resolve` runs metabolite mapping for the universal path too), so
  candidates can be metabolite-reconciled and reach High.
- `confidence_score` is a legacy tier-derived ordering/export field only, not a
  biological probability.
- KEGG substrate/product matching excludes common currency metabolites; a side
  with no informative (non-currency) compounds on either the model or KEGG side
  is `unverifiable`, not a match.
- Default candidate evidence behavior is eager: all extracted candidate
  reactions are evaluated before gap-filling. `Config.candidate_evidence_eager_limit`
  is `0` by default; set it to a positive threshold to defer evidence for large
  universals and evaluate only gap-filled reactions.
- CLI gap-fill mode accepts draft model, universal model, metabolic task CSV,
  and optional base medium. Metabolic tasks are self-contained — each task's
  `Medium` column declares the full medium it needs, and `prepare_task_model`
  opens trace elements/water/protons. The draft model's default medium is NOT
  auto-merged when `--medium` is omitted: doing so would add nutrients (e.g.
  glucose) back into negative-constraint tasks that omit them on purpose
  ("no X without carbon source"), breaking those tests and making CLI disagree
  with the GUI. Only an EXPLICIT `--medium` (JSON, CSV/TSV, or inline spec such
  as `glc__D_e(-10);o2_e(-1000)`) is merged as a base medium, in BOTH CLI and
  GUI. A complete model (e.g. iML1515) passes all 52 universal tasks with
  task-only media.
- Gap-filling is metabolic-task-aware. Task evaluation and gap-fill setup share
  `TaskRunner.prepare_task_model()` so medium, free exchanges, trace elements,
  cofactor turnover, constraints, and ID normalization stay consistent.
- Negative or upper-bound tasks are not gap-fillable and are skipped by the
  reaction-addition repair step.
- Exchange/demand/sink boundary reactions are excluded from gap-fill candidates
  and from the COBRApy solver universal by default
  (`Config.gapfill_exclude_exchange_reactions = True`). CLI/GUI controls can
  explicitly include them for specialized workflows.
- Previously passing tasks are protected during gap-fill. Candidate sets that
  would break them are discarded, and an applied iteration is rolled back if
  final task retesting still shows protected-task regressions.
- The gap-fill workflow has an outer convergence loop controlled by
  `Config.gapfill_iterations`.
- `Config.gapfill_alternatives` controls per-task alternative solution search.
  If an alternative breaks a protected task, the next alternative is tried; if
  no alternative preserves protected tasks, that task's gap-fill attempt fails.
- Gap-fill penalties are based on evidence tier, then adjusted by KEGG organism
  presence/absence and missing KEGG reaction IDs. Do not use legacy numeric
  confidence as the primary biological penalty signal.
- Large universal models are pruned for MILP solving when above
  `Config.gapfill_universal_prune_threshold`, keeping reactions compatible with
  the draft model metabolite set plus explicit task targets.

## Project Structure

```text
src/
├── api/                 # Async KEGG client + base infrastructure
│   ├── base_client.py   # Rate limiting, retry, circuit breaker base class
│   ├── kegg_client.py   # KEGG evidence checks (reconciliation + EC concordance)
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
├── evidence/            # KEGG-only candidate evidence orchestration + rule-based tiers
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
  - strict KEGG-only candidate universe (only KEGG-mapped reactions addable),
  - candidate KEGG evidence weighting (tier → penalty) and gap-fill report provenance.
