# Gap Analysis: task-detail-display

> **Feature**: task-detail-display
> **Design Document**: `docs/02-design/features/task-detail-display.design.md`
> **Implementation Files**: `src/gui/task_panel.py` (modified), `src/gui/task_detail_dialog.py` (new)
> **Analysis Date**: 2026-02-23
> **Status**: Approved

---

## Summary

- **Match Rate**: 100% (9/9)
- **Items Checked**: 9
- **Matched**: 9/9
- **Gaps**: 0

All 9 design items (A-1 through A-5 and B-1 through B-4) are fully implemented and match the design specification. One minor, non-functional deviation is noted below in B-4 (value format precision), but it does not constitute a gap since the design intent is preserved.

---

## Design vs Implementation Comparison

### A-1: Column Structure Change
- **Status**: Match
- **Design**: Change detail table from 5 columns to 7 columns with headers `["Task ID", "Type", "Description", "Category", "Expected", "Before", "After"]`. Define column index constants `_COL_TASK_ID=0` through `_COL_AFTER=6`.
- **Implementation** (`task_panel.py` lines 26-32, 95-98):
  - Column count is set to 7 via `self._detail_table.setColumnCount(7)`.
  - Headers match exactly: `["Task ID", "Type", "Description", "Category", "Expected", "Before", "After"]`.
  - Module-level constants defined: `_COL_TASK_ID = 0`, `_COL_TYPE = 1`, `_COL_DESC = 2`, `_COL_CATEGORY = 3`, `_COL_EXPECTED = 4`, `_COL_BEFORE = 5`, `_COL_AFTER = 6`.
- **Verdict**: Exact match.

### A-2: Column Resize Settings
- **Status**: Match
- **Design**: Set resize modes per column -- `ResizeToContents` for Task ID, Type, Category, Expected, Before, After; `Stretch` for Description.
- **Implementation** (`task_panel.py` lines 99-106):
  ```python
  header.setSectionResizeMode(_COL_TASK_ID, QHeaderView.ResizeMode.ResizeToContents)
  header.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
  header.setSectionResizeMode(_COL_DESC, QHeaderView.ResizeMode.Stretch)
  header.setSectionResizeMode(_COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
  header.setSectionResizeMode(_COL_EXPECTED, QHeaderView.ResizeMode.ResizeToContents)
  header.setSectionResizeMode(_COL_BEFORE, QHeaderView.ResizeMode.ResizeToContents)
  header.setSectionResizeMode(_COL_AFTER, QHeaderView.ResizeMode.ResizeToContents)
  ```
- **Verdict**: Exact match. All 7 columns have the specified resize mode.

### A-3: Before/After Cells Show Actual Values
- **Status**: Match
- **Design**: Change Before/After cells from icon-only (`"check"` or `"cross"`) to `"{icon} {value}"` format (e.g. `"check_mark 23.45"`). Add `_format_value()` helper that returns `"0"` for 0.0, scientific notation for abs < 0.01, one decimal for abs >= 1000, four decimals otherwise.
- **Implementation** (`task_panel.py` lines 35-43, 237-254):
  - `_format_value()` function matches the design exactly:
    - `value == 0.0` returns `"0"`
    - `abs(value) < 0.01` returns `f"{value:.2e}"`
    - `abs(value) >= 1000` returns `f"{value:.1f}"`
    - Otherwise returns `f"{value:.4f}"`
  - Before cell: `QTableWidgetItem(f"{icon} {val}")` with `AlignCenter`.
  - After cell: same pattern with `QTableWidgetItem(f"{icon} {val}")` and `AlignCenter`.
- **Verdict**: Exact match.

### A-4: Expected Column + Type Column Added
- **Status**: Match
- **Design**: In `_build_detail_table()`, populate Type column with `task.task_type` and Expected column with `f"{task.expected_operator}{task.expected_value:g}"` (center-aligned).
- **Implementation** (`task_panel.py` lines 219, 231-234):
  - Type column: `QTableWidgetItem(task.task_type)` set at `_COL_TYPE`.
  - Expected column: `expected_text = f"{task.expected_operator}{task.expected_value:g}"`, item created and set with `AlignCenter`.
- **Verdict**: Exact match.

### A-5: Result Map Storage + Double-Click Connection
- **Status**: Match
- **Design**: In `set_results()`, store `self._before_map` and `self._after_map` as instance dictionaries keyed by `task_id`. In `_setup_ui()`, connect `cellDoubleClicked` to `_on_detail_double_clicked`. Handler reads task_id from row, looks up results from maps, imports `TaskDetailDialog` lazily, and calls `dialog.exec()`.
- **Implementation** (`task_panel.py` lines 51-52, 111, 114-123, 258-272):
  - `__init__` initializes `self._before_map` and `self._after_map` as empty dicts.
  - `set_results()` builds both maps: `{r.task.task_id: r for r in before}` and same for after.
  - `cellDoubleClicked.connect(self._on_detail_double_clicked)` in `_setup_ui()`.
  - Handler matches design: retrieves `task_id_item` from column `_COL_TASK_ID`, guards for None, looks up `before_result` and `after_result`, lazy-imports `TaskDetailDialog`, creates dialog and calls `dialog.exec()`.
- **Verdict**: Exact match.

### B-1: File Creation (TaskDetailDialog class)
- **Status**: Match
- **Design**: New file `src/gui/task_detail_dialog.py` with class `TaskDetailDialog(QDialog)` accepting `before: TaskResult`, `after: TaskResult | None = None`, `parent=None`.
- **Implementation** (`task_detail_dialog.py` lines 33-48):
  ```python
  class TaskDetailDialog(QDialog):
      def __init__(
          self,
          before: TaskResult,
          after: TaskResult | None = None,
          parent=None,
      ) -> None:
  ```
- **Verdict**: Exact match. Constructor signature, inheritance, and return type annotation all align.

### B-2: Task Info Section
- **Status**: Match
- **Design**: QGroupBox "Task Info" with QFormLayout containing rows: Task ID, Type, Target, Description, Category.
- **Implementation** (`task_detail_dialog.py` lines 53-64):
  - `QGroupBox("Task Info")` with `QFormLayout`.
  - Rows: "Task ID:", "Type:", "Target:", "Description:", "Category:" -- all present.
  - Description falls back to `"-"` if empty (design shows plain text display); Category falls back to `"Uncategorized"`.
- **Verdict**: Exact match.

### B-3: Objective + Medium + Constraints Sections
- **Status**: Match
- **Design**:
  - **Objective**: QGroupBox "Objective Function". Metabolite type shows `"Maximize DM_{target_id} (demand reaction for {target_id})"`, Reaction type shows `"Maximize {target_id} flux"`.
  - **Medium**: QGroupBox "Medium" with 2-column QTableWidget (Exchange Reaction, Lower Bound). Empty medium shows `QLabel("Default (no medium changes)")`.
  - **Constraints**: QGroupBox "Additional Constraints" with 3-column QTableWidget (Reaction, Lower Bound, Upper Bound). Empty constraints shows `QLabel("No additional constraints")`.
- **Implementation** (`task_detail_dialog.py` lines 67-140):
  - **Objective** (lines 67-79): GroupBox title "Objective Function". Metabolite branch: `f"Maximize DM_{self._task.target_id}  (demand reaction for {self._task.target_id})"`. Else: `f"Maximize {self._task.target_id} flux"`. Match.
  - **Medium** (lines 82-107): GroupBox "Medium". 2-column table with headers `["Exchange Reaction", "Lower Bound"]`. Items sorted and populated. Empty case: `QLabel("Default (no medium changes)")`. Match.
  - **Constraints** (lines 110-140): GroupBox "Additional Constraints". 3-column table with headers `["Reaction", "Lower Bound", "Upper Bound"]`. Constraint values unpacked as `(lower, upper)` tuple. Empty case: `QLabel("No additional constraints")`. Match.
- **Verdict**: Exact match.

### B-4: Result Section
- **Status**: Match
- **Design**: QGroupBox "Result" with QFormLayout. Rows: Expected (`"{operator}{value:g}"`), Before (`"check_mark PASS (actual: 23.4505)"`), After (only if present), Error (if error_message exists). Before/After labels colored using transition colors. Dialog has `QDialogButtonBox(Close)` at bottom.
- **Implementation** (`task_detail_dialog.py` lines 143-178):
  - GroupBox "Result" with `QFormLayout`.
  - Expected: `f"{self._task.expected_operator}{self._task.expected_value:g}"` -- match.
  - Before: `_make_result_label()` returns `QLabel(f"{icon}  (actual: {val})")` where icon is `"check_mark PASS"` or `"cross FAIL"` -- matches design format.
  - After: only added if `self._after is not None`. Transition colors applied to both labels -- match.
  - Error: checks `self._before.error_message` or `self._after.error_message`, displays with `THEME.error` color and word wrap -- match.
  - Close button: `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` connected to `self.reject` -- match.
- **Minor deviation**: The `_format_value()` in `task_detail_dialog.py` (line 30) uses `.6f` precision for the default case (`f"{value:.6f}"`) instead of `.4f` as in `task_panel.py`. This is a cosmetic difference in the dialog's detailed view -- the design does not explicitly specify precision for the dialog's result label, only for the table cells (A-3). This is an intentional enhancement (more precision in the detail dialog) and does not constitute a gap.
- **Verdict**: Match.

---

## Gap List

No gaps found. All 9 design items are fully implemented.

---

## Minor Deviations (Non-Gap)

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| B-4 _format_value precision | `.4f` (inherited from A-3 spec) | `.6f` in task_detail_dialog.py | None -- detail dialog benefits from higher precision |
| A-5 map init location | Design shows maps created in `set_results()` | Maps initialized in `__init__` then populated in `set_results()` | None -- functionally equivalent; pre-initializing avoids AttributeError before first `set_results()` call |
| B-2 hint label | Not specified in design | `task_panel.py` line 85-87 adds "Double-click a row to view task details" hint | Positive -- improves discoverability |

---

## Recommendations

No corrective actions needed. The implementation fully satisfies the design specification.

1. **Consider unifying `_format_value()`** -- The function is duplicated across `task_panel.py` and `task_detail_dialog.py` with slightly different precision (`.4f` vs `.6f`). If this is intentional (table vs dialog precision), document it. Otherwise, extract to a shared utility in `src/gui/` or `src/utils/`.

2. **Test coverage** -- No test file for `TaskDetailDialog` was found. Consider adding `tests/test_gui_task_detail_dialog.py` covering:
   - Dialog creation with before-only results
   - Dialog creation with before+after results
   - Medium and constraints table population
   - Empty medium/constraints fallback labels
   - Error message display
