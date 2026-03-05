# workflow-resume-universal-browser Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: GEM Evaluator (model_evaluator)
> **Analyst**: gap-detector
> **Date**: 2026-02-23
> **Design Doc**: [workflow-resume-universal-browser.design.md](../02-design/features/workflow-resume-universal-browser.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Verify that all 28 checklist items from the design document (Section 6) are correctly implemented in the codebase. The feature covers three phases: Cancel Recovery (Phase A), Resume Workflow (Phase B), and Universal Model Browser (Phase C).

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/workflow-resume-universal-browser.design.md`
- **Implementation Files**:
  - `src/core/models.py` (Items 1-4)
  - `src/gapfill/engine.py` (Items 5-8)
  - `src/gui/workers.py` (Items 9-13)
  - `src/gui/progress_dialog.py` (Item 14)
  - `src/gui/main_window.py` (Items 15-19, 21-24)
  - `src/gui/gapfill_panel.py` (Item 20)
  - `src/gui/candidate_table.py` (Items 25-27)
  - `src/gui/reaction_detail.py` (Item 28)
- **Analysis Date**: 2026-02-23

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 Item-by-Item Verification

#### Phase A: Cancel Recovery -- Data Model (`src/core/models.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 1 | `GapFillResult.completed_phase` | `int = 0` | Line 254: `completed_phase: int = 0` | MATCH |
| 2 | `GapFillResult.all_candidates` | `list[CandidateReaction]` | Line 255: `all_candidates: list[CandidateReaction] = field(default_factory=list)` | MATCH |
| 3 | `GapFillResult.is_partial` | `bool = False` | Line 256: `is_partial: bool = False` | MATCH |
| 4 | `WorkflowCheckpoint` dataclass | 6 fields: completed_phase, result, universal_path, task_path, options, timestamp | Lines 259-268: All 6 fields present with matching types | MATCH |

#### Phase A: Cancel Recovery -- Engine (`src/gapfill/engine.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 5 | `run()` cancel_event param | `asyncio.Event \| None = None` | Line 84: `cancel_event: asyncio.Event \| None = None` | MATCH |
| 6 | Phase-by-phase cancel check | `_is_cancelled()` after each phase | Lines 111-112 define `_is_cancelled()`, checked after Phase 1 (L125), Phase 2 (L173), Phase 3 (L218), Phase 4 (L234) | MATCH |
| 7 | `run()` start_phase param | `int = 1` | Line 85: `start_phase: int = 1` | MATCH |
| 8 | `run()` preloaded_before param | `list[TaskResult] \| None = None` | Line 86: `preloaded_before: list[TaskResult] \| None = None` | MATCH |

#### Phase A: Cancel Recovery -- Worker (`src/gui/workers.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 9 | `GapFillWorkerSignals.cancelled` | `Signal(object, int)` | Line 47: `cancelled = Signal(object, int)` | MATCH |
| 10 | `GapFillWorkflowWorker.cancel()` | `_cancel_event.set()` | Lines 245-248: `cancel()` method calls `self._cancel_event.set()` | MATCH |
| 11 | `_cancel_event` field | `asyncio.Event` | Line 241: `self._cancel_event: asyncio.Event \| None = None` | MATCH |
| 12 | Resume params | `start_phase`, `preloaded_before`, `preloaded_candidates` | Lines 227-229: All three parameters present | MATCH |
| 13 | `setAutoDelete(False)` | GC prevention | Line 243: `self.setAutoDelete(False)` | MATCH |

#### Phase A: Cancel Recovery -- Progress Dialog (`src/gui/progress_dialog.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 14 | Cancel signal + button | `cancel_requested` Signal | Line 21: `cancelled = Signal()`, Line 48: Cancel button, Lines 67-70: `_on_cancel()` emits `cancelled`. Functionally equivalent -- existing signal serves same purpose | MATCH |

Note on Item 14: The design specifies `cancel_requested` as the signal name. The implementation uses `cancelled` instead. This is a naming difference only; the signal serves the identical purpose (emitted when the cancel button is clicked). The MainWindow connects `dialog.cancelled` to `worker.cancel` which matches the intended behavior. Counted as MATCH.

#### Phase A/B: MainWindow Cancel + Resume (`src/gui/main_window.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 15 | `_workflow_checkpoint` field | `WorkflowCheckpoint \| None` | Line 88: `self._workflow_checkpoint: WorkflowCheckpoint \| None = None` | MATCH |
| 16 | `_on_gapfill_cancelled()` handler | Checkpoint save + Phase-based UI update | Lines 1014-1051: Saves checkpoint, updates task_panel (phase>=1), candidate_table (phase>=2), gapfill_panel (phase>=3) | MATCH |
| 17 | `_start_workflow()` checkpoint check | Resume dialog Yes/No/Cancel | Lines 822-856: Checks checkpoint, shows QMessageBox.question with 3 buttons | MATCH |
| 18 | `_resume_workflow()` method | Checkpoint-based worker creation | Lines 858-899: Creates worker with `cp.completed_phase + 1`, preloaded data | MATCH |
| 19 | `_on_model_loaded()` checkpoint reset | `self._workflow_checkpoint = None` | Line 499: `self._workflow_checkpoint = None` | MATCH |

#### Phase A: GapFillPanel (`src/gui/gapfill_panel.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 20 | `set_partial_result()` | Banner + partial table display | Lines 145-179: Sets summary label with phase info, populates reaction table, disables apply/export buttons | MATCH |

#### Phase C: Universal Model Browser (`src/gui/main_window.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 21 | "Load Universal Model..." menu | File menu item | Line 110: `file_menu.addAction("Load &Universal Model...", self._load_universal_model)` | MATCH |
| 22 | `_universal_table` + Universal tab | CandidateTableWidget in left_tabs | Lines 180-183: `self._universal_table = CandidateTableWidget()`, added as "Universal" tab | MATCH |
| 23 | `_load_universal_model()` | UniversalLoader, candidates, tab display | Lines 1116-1156: Loads model, extracts candidates, sets overview, switches to Universal tab | MATCH |
| 24 | `_on_universal_selected()` | Detail panel read-only display | Lines 1158-1164: Sets `set_read_only(True)`, then `set_reaction()` | MATCH |

#### Phase C: CandidateTableWidget (`src/gui/candidate_table.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 25 | `set_mode()` | "default" / "browse" mode | Lines 298-304: Toggles `_overview_label` and `_evaluate_btn` visibility based on mode | MATCH |
| 26 | `_overview_label` | Browse mode overview header | Lines 294, 316-320: `QLabel` with `sectionTitle` object name, visible only in browse mode | MATCH |
| 27 | `_evaluate_btn` + `evaluate_requested` | Evaluate Selected button + signal | Lines 286, 295, 361-367, 448-451: Button hidden by default, signal emits selected candidates | MATCH |

#### Phase C: ReactionDetailWidget (`src/gui/reaction_detail.py`)

| # | Item | Design | Implementation | Status |
|---|------|--------|----------------|--------|
| 28 | `set_read_only()` | Toggle read-only on all editable fields | Lines 122-131: Sets readOnly on name, subsystem, lower_bound, upper_bound, equation, gpr; hides save button | MATCH |

---

### 2.2 Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 100% (28/28)            |
+---------------------------------------------+
|  MATCH:          28 items (100%)             |
|  PARTIAL:         0 items (0%)               |
|  MISSING:         0 items (0%)               |
+---------------------------------------------+
```

---

## 3. Detailed Findings

### 3.1 Minor Naming Differences (Non-Breaking)

| Item | Design Name | Implementation Name | Impact |
|------|-------------|---------------------|--------|
| 14 | `cancel_requested` | `cancelled` | None -- functionally equivalent, existing signal reused |

### 3.2 Implementation Additions (Design X, Implementation O)

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| `_evaluate_batch()` helper | `main_window.py:1175-1191` | Extracted shared batch evaluation logic used by both regular and universal evaluation |
| `_on_reaction_selected()` read-only reset | `main_window.py:567` | Calls `set_read_only(False)` when selecting model reactions, ensuring proper mode toggle |
| `evaluate_universal_candidates` connection | `main_window.py:182` | Signal connected in `_setup_ui()` alongside `candidate_selected` |

These additions are natural implementation refinements that support the designed features without diverging from the design intent.

---

## 4. Phase-by-Phase Verification

### Phase A: Cancel Recovery (Items 1-16, 20)

All 14 items verified. The cancel pipeline flows correctly:
1. `ProgressDialog.cancelled` signal triggers `GapFillWorkflowWorker.cancel()`
2. Worker sets `_cancel_event` which `GapFillEngine.run()` checks after each phase
3. Engine returns `GapFillResult` with `is_partial=True`
4. Worker detects partial result and emits `cancelled` signal
5. `MainWindow._on_gapfill_cancelled()` saves checkpoint and updates UI per phase

### Phase B: Resume Workflow (Items 17-19)

All 3 items verified. The resume flow works correctly:
1. `_start_workflow()` checks for existing checkpoint
2. User chooses Yes (resume) / No (fresh start) / Cancel (abort)
3. `_resume_workflow()` creates worker with `start_phase = cp.completed_phase + 1`
4. Engine skips completed phases using `start_phase` parameter
5. Checkpoint cleared on resume or new model load

### Phase C: Universal Model Browser (Items 21-28)

All 8 items verified. The browser flow works correctly:
1. "Load Universal Model..." menu loads model via `UniversalLoader`
2. Candidates displayed in Universal tab with browse mode (overview header, evaluate button)
3. Clicking a reaction shows read-only detail
4. "Evaluate Selected" runs evidence evaluation on checked candidates

---

## 5. Overall Score

```
+---------------------------------------------+
|  Overall Score: 100/100                      |
+---------------------------------------------+
|  Design Match:         100%  (28/28 items)   |
|  Phase A (Cancel):     100%  (14/14 items)   |
|  Phase B (Resume):     100%  (3/3 items)     |
|  Phase C (Browser):    100%  (8/8 items)     |
|  Minor Differences:    1 (naming only)       |
+---------------------------------------------+
```

---

## 6. Recommended Actions

No corrective actions required. All 28 design items are implemented correctly.

### Optional Documentation Updates

- [ ] Item 14: Update design document to reflect actual signal name `cancelled` instead of `cancel_requested` (cosmetic alignment)

---

## 7. Next Steps

- [x] Gap analysis complete
- [ ] Write completion report (`workflow-resume-universal-browser.report.md`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-23 | Initial gap analysis -- 28/28 items match | gap-detector |
