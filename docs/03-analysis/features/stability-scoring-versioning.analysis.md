# stability-scoring-versioning Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: GEM Evaluator
> **Analyst**: gap-detector agent
> **Date**: 2026-02-21
> **Design Doc**: [stability-scoring-versioning.design.md](../../02-design/features/stability-scoring-versioning.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Verify that the implementation of the stability-scoring-versioning feature
(Phases A, B, and C) matches the design document specification.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/stability-scoring-versioning.design.md`
- **Implementation Paths**: `src/gui/`, `src/core/`, `src/gapfill/`, `src/versioning/`, `src/utils/`, `tests/`
- **Analysis Date**: 2026-02-21

---

## 2. Gap Analysis (Design vs Implementation)

### Phase A: Stability Fixes (already completed by lead)

| # | Item | Design Location | Implementation File | Status | Notes |
|---|------|----------------|---------------------|--------|-------|
| 1 | `_safe_emit()` function exists; all signal emits use it | design:14 | `src/gui/workers.py:23-28` | MATCH | Function defined at line 23; every `.emit()` call in the file goes through `_safe_emit()` (confirmed via grep -- only `signal.emit(*args)` inside `_safe_emit` itself) |
| 2 | `InitEngineWorker`, `CloseEngineWorker`, `LoadModelWorker` have `setAutoDelete(False)` | design:15 | `src/gui/workers.py:134,162,189` | MATCH | `InitEngineWorker` line 134, `CloseEngineWorker` line 162, `LoadModelWorker` line 189 |
| 3 | `_active_workers` is a `list[object]` (not singular `_active_worker`) | design:16 | `src/gui/main_window.py:84` | MATCH | `self._active_workers: list[object] = []` at line 84 |
| 4 | `warnings.catch_warnings()` in `load_model()` | design:18 | `src/core/sbml_parser.py:29-31` | MATCH | `with warnings.catch_warnings(): warnings.simplefilter("ignore")` wraps `cobra.io.read_sbml_model()` |

### Phase B: Score-Based Gap-Fill

| # | Item | Design Location | Implementation File | Status | Notes |
|---|------|----------------|---------------------|--------|-------|
| 5 | Penalty dict passed to `gapfill()`, results sorted by score | design:28 | `src/gapfill/engine.py:351-355,165-172` | MATCH | `penalties=penalties` passed to `cobra.flux_analysis.gapfilling.gapfill()` at line 355; `result.added_reactions.sort(key=..., reverse=True)` at lines 165-172 sorts by evidence score descending |
| 6 | `candidate_table.py` default sort Score descending | design:29 | `src/gui/candidate_table.py:380-383` | MATCH | `self._table.sortByColumn(CandidateTableModel.COL_SCORE, Qt.SortOrder.DescendingOrder)` in `set_candidates()` |
| 7 | `gapfill_panel.py` added reactions sorted by Score descending | design:30 | `src/gui/gapfill_panel.py:127` | MATCH | `self._reaction_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)` at line 127 |

### Phase C: New Files

| # | Item | Design Location | Implementation File | Status | Notes |
|---|------|----------------|---------------------|--------|-------|
| 8 | `src/versioning/__init__.py` exists | design:38 | `src/versioning/__init__.py` | MATCH | Exists with docstring |
| 9 | `src/versioning/diff_engine.py` -- `DiffEngine` with `compute_diff()` | design:143-183 | `src/versioning/diff_engine.py` | MATCH | `DiffEngine` class with `compute_diff(old_model, new_model) -> ModelDiff`, `_compare_reactions()`, `_diff_reaction()`. Compares reactions (added/removed/modified by bounds, GPR, name, subsystem), genes, metabolites. |
| 10 | `src/versioning/storage.py` -- `VersionStorage` with all 6 methods | design:185-234 | `src/versioning/storage.py` | MATCH | All methods present: `save_version()` (line 41), `load_version()` (line 79), `load_history()` (line 108), `save_history()` (line 117), `cleanup_old_versions()` (line 130), `get_next_version_id()` (line 160). Directory layout matches design: `{base_dir}/{model_id}/v{NNN}/model.xml + meta.json` |
| 11 | `src/versioning/version_manager.py` -- `VersionManager` with full API | design:236-290 | `src/versioning/version_manager.py` | MATCH | All methods: `set_base_model()` (line 37), `async save_version()` (line 65), `restore_version()` (line 130), `get_history()` (line 168), `compare_versions()` (line 172), `current_version` property (line 180). Init matches: stores `_storage`, `_diff_engine`, `_summarizer`, `_current_version`, `_previous_model`. |
| 12 | `src/versioning/change_summarizer.py` -- `ChangeSummarizer` with `summarize()`, `_template_summary()` | design:292-323 | `src/versioning/change_summarizer.py` | MATCH | `ChangeSummarizer(config)` with `async summarize(diff, change_type)` (line 23) and `_template_summary(diff, change_type)` (line 41). LLM via Gemini with template fallback. All 4 change types handled: `initial_load`, `gap_fill`, `manual_edit`, `restore`. |
| 13 | `src/gui/save_dialog.py` -- `SaveDialog(QDialog)` with `get_options()` | design:325-358 | `src/gui/save_dialog.py` | MATCH | `SaveDialog(QDialog)` with `__init__(config, current_version, parent)` and `get_options() -> dict` returning `{change_type, description, run_qc, export_sbml}`. UI layout matches design wireframe. |
| 14 | `src/gui/version_panel.py` -- `VersionPanelWidget` with signals | design:360-383 | `src/gui/version_panel.py` | MATCH | `VersionPanelWidget(QWidget)` with `set_history()` (line 70), `clear()` (line 81). Signals: `restore_requested = Signal(str)` (line 27), `compare_requested = Signal(str, str)` (line 28), `export_requested = Signal(str)` (line 29). |
| 15 | `src/gui/diff_dialog.py` -- `DiffDialog(QDialog)` with ModelDiff display | design:385-418 | `src/gui/diff_dialog.py` | MATCH | `DiffDialog(QDialog)` with `__init__(diff, version_a, version_b, parent)`. Shows reactions added/removed/modified tables, QC comparison, genes/metabolites summary. Layout matches design wireframe. |

### Phase C: Modified Files

| # | Item | Design Location | Implementation File | Status | Notes |
|---|------|----------------|---------------------|--------|-------|
| 16 | `src/core/models.py` -- `ReactionChange`, `ModelDiff` (with `is_empty`, `summary_counts`), `ModelVersion` | design:61-120 | `src/core/models.py:257-315` | MATCH | `ReactionChange` (line 258), `ModelDiff` with `is_empty` property (line 280) and `summary_counts` property (line 288), `ModelVersion` (line 304). All fields match design spec exactly. |
| 17 | `src/utils/config.py` -- `enable_versioning`, `max_versions`, `auto_save_on_edit`, `version_dir` | design:122-130 | `src/utils/config.py:63-66` | MATCH | `enable_versioning: bool = True` (line 63), `max_versions: int = 20` (line 64), `auto_save_on_edit: bool = True` (line 65), `version_dir: str = ""` (line 66) |
| 18 | `src/utils/constants.py` -- `VERSION_DIR`, `MAX_VERSIONS_DEFAULT` | design:132-137 | `src/utils/constants.py:71-72` | MATCH | `VERSION_DIR = CONFIG_DIR / "versions"` (line 71), `MAX_VERSIONS_DEFAULT = 20` (line 72) |
| 19 | `src/gui/main_window.py` -- version manager field, Save Version menu, Versions tab, all version methods, model loaded init, gapfill auto-save, reaction modified auto-save | design:420-463 | `src/gui/main_window.py` | MATCH | All items verified: `_version_manager` field (line 86), "Save Version..." menu action (line 108), Versions tab (line 229), `_save_version()` (line 1079), `_restore_version()` (line 1151), `_compare_versions()` (line 1176), `_on_model_loaded` inits VersionManager (lines 528-535), `_on_gapfill_complete` auto-saves (lines 921-926), `_on_reaction_modified` auto-saves (lines 1069-1075) |

### Phase C: Tests

| # | Item | Design Location | Implementation File | Status | Notes |
|---|------|----------------|---------------------|--------|-------|
| 20 | `tests/test_diff_engine.py` exists with tests | design:46 | `tests/test_diff_engine.py` | MATCH | 209 lines, 4 test classes (TestDiffEngineReactions, TestDiffEngineGenes, TestDiffEngineMetabolites, TestDiffEngineEmpty) covering added/removed/modified reactions, genes, metabolites, empty scenarios, summary_counts |
| 21 | `tests/test_version_manager.py` exists with tests | design:47 | `tests/test_version_manager.py` | MATCH | 378 lines, covers VersionStorage (save/load, history, cleanup, next_id) and VersionManager (set_base, save, restore, history, compare). 17 test methods total. |
| 22 | `tests/test_change_summarizer.py` exists with tests | design:48 | `tests/test_change_summarizer.py` | MATCH | 200 lines, covers template summaries for all 4 change types, async summarize with and without LLM, fallback on LLM error, LLM prompt construction. 14 test methods total. |

---

## 3. Match Rate Summary

```
Total Items:   22
MATCH:         22
PARTIAL:        0
MISSING:        0

Match Rate:    100% (22/22)
```

| Category | Items | Matched | Score | Status |
|----------|:-----:|:-------:|:-----:|:------:|
| Phase A: Stability | 4 | 4 | 100% | MATCH |
| Phase B: Score-Based Gap-Fill | 3 | 3 | 100% | MATCH |
| Phase C: New Files | 8 | 8 | 100% | MATCH |
| Phase C: Modified Files | 4 | 4 | 100% | MATCH |
| Phase C: Tests | 3 | 3 | 100% | MATCH |
| **Overall** | **22** | **22** | **100%** | **MATCH** |

---

## 4. Minor Implementation Differences (not affecting match rate)

These are implementation details that differ slightly from the design but are
equivalent or improved:

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| Save shortcut | `Ctrl+S` | `Ctrl+Shift+S` | Low -- avoids conflict with Export CSV which uses `Ctrl+S` |
| `DiffDialog` import | (not specified) | Imports `THEME` from `src/gui/theme` | None -- styling enhancement |
| `_on_reaction_modified` auto-save | Calls `save_version` directly | Calls `_auto_save_version()` helper | None -- cleaner separation |
| `VersionManager.save_version` | returns `ModelVersion` | Returns `ModelVersion` (same) | None |

---

## 5. Recommended Actions

Match rate is 100%. Design and implementation are fully synchronized.

No immediate actions required.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-21 | Initial analysis | gap-detector |
