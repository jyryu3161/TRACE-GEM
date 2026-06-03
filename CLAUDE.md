# GEM Evaluator

Genome-Scale Metabolic Model Evidence Evaluator. Evaluates reactions in SBML models against KEGG and BiGG evidence to compute confidence scores.

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

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing

# Lint and format
ruff check src/ tests/ --fix
ruff format src/ tests/

# Type check
mypy src/ --ignore-missing-imports

# Pre-commit (all hooks)
pre-commit run --all-files
```

## Project Structure

```
src/
├── core/          # Data models, SBML parsing, GPR parsing, ID mapping
│   ├── models.py       # Dataclasses: Reaction, ModelData, EvidenceItem, etc.
│   ├── sbml_parser.py  # COBRApy-based SBML loader
│   ├── gpr_parser.py   # Gene-Protein-Reaction rule parser
│   └── id_mapper.py    # BiGG → external DB ID resolution
├── api/           # External API clients (all async)
│   ├── base_client.py  # ABC with rate limiting, retry, circuit breaker
│   ├── rate_limiter.py # Token-bucket rate limiter
│   ├── bigg_client.py
│   ├── kegg_client.py
│   └── bigg_lookup.py
├── evidence/      # Evidence collection and scoring
│   ├── engine.py       # Orchestrator: queries KEGG/BiGG per reaction
│   ├── scoring.py      # Weighted confidence scoring
│   └── evidence_types.py # Thresholds and display constants
├── gui/           # PySide6 (Qt6) GUI
│   ├── main_window.py  # Main app window, menus, export
│   ├── workers.py      # QRunnable workers (async in worker threads)
│   ├── reaction_table.py   # Table model + filter proxy + widget
│   ├── delegates.py    # Score bar and status cell renderers
│   ├── model_overview.py
│   ├── reaction_detail.py
│   ├── evidence_panel.py
│   ├── gene_panel.py
│   ├── metabolite_panel.py
│   ├── score_visualization.py  # PyQtGraph charts
│   ├── progress_dialog.py
│   ├── settings_dialog.py
│   └── styles.py
├── cache/         # SQLite caching layer
│   ├── cache_manager.py
│   └── schema.py
├── utils/         # Configuration, logging, constants
│   ├── config.py
│   ├── constants.py
│   └── logging_config.py
└── app.py         # Entry point
```

## Tech Stack

- **SBML Parsing**: COBRApy (wraps libsbml)
- **GUI**: PySide6 (Qt6) + PyQtGraph
- **DB APIs**: Biopython (KEGG), aiohttp (REST), BiGG local lookup
- **Caching**: SQLite via aiosqlite
- **Async**: QRunnable workers + asyncio event loops in worker threads

## Conventions

- Python 3.10+, type hints on all functions
- `from __future__ import annotations` in every module
- Dataclasses for data models, ABC for client interfaces
- asyncio for all API calls — always in worker threads, never on the GUI thread
- SQLite cache with configurable TTL per source
- See `style.md` for detailed coding standards

## Testing

- pytest + pytest-asyncio + pytest-qt
- `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio` on fixtures
- All external API calls must be mocked in tests
- Fixtures in `tests/conftest.py`, mock data in `tests/fixtures/`
- GUI tests use `qtbot` fixture from pytest-qt
