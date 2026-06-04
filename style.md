# MetaTaskGapFill — Style Guide

## Python Conventions

- Python 3.10+ required
- `from __future__ import annotations` at the top of every module
- Type hints on all function signatures (parameters and return types)
- Use `dataclasses` for data models, `ABC` for client interfaces
- Use `Optional[X]` or `X | None` for nullable types

## Naming

- `snake_case` for functions, methods, variables, modules
- `PascalCase` for classes
- `UPPER_CASE` for module-level constants
- Private members prefixed with `_` (single underscore)
- No double-underscore name mangling

## Imports

Order (enforced by ruff `I` rule):
1. Standard library (`import os`, `from pathlib import Path`)
2. Third-party (`import aiohttp`, `from PySide6.QtCore import ...`)
3. Local (`from src.core.models import Reaction`)

One blank line between each group.

## Async Patterns

- All API calls use `async/await`
- GUI thread must never run async code directly
- Use `QRunnable` workers that create their own `asyncio.new_event_loop()`
- Workers communicate results back via `Signal`/`Slot`
- Never share event loops between threads

## Error Handling

- Fail fast with meaningful error messages
- Log with context: `logger.warning("[%s] message: %s", client_name, error)`
- Use circuit breaker pattern for external APIs (5 failures → 5 min cooldown)
- Catch specific exceptions, not bare `except:`

## GUI Patterns

- Signals/slots for cross-thread communication
- `QRunnable` + `QThreadPool` for background tasks
- All long operations (model loading, API queries) run in workers
- Status bar for user feedback
- Modal `QDialog` for settings, progress

## Testing

- pytest with pytest-asyncio (auto mode) and pytest-qt
- Mock all external API calls — no network in tests
- Fixtures in `tests/conftest.py`
- Test file naming: `test_{module}.py`
- Use `qtbot` fixture for GUI widget tests
- Use `tmp_path` for file-based tests (cache, config)
