"""Metabolic task results panel showing before/after gap-filling comparison."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.models import TaskResult
from src.gui.theme import THEME

# Color coding for task status transitions
_COLOR_PASS_PASS = "#27ae60"   # green: passed both before and after
_COLOR_FAIL_PASS = "#3498db"   # blue: fixed (fail -> pass)
_COLOR_FAIL_FAIL = "#e74c3c"   # red: still failing
_COLOR_PASS_FAIL = "#e67e22"   # orange: regressed (pass -> fail)

# Detail table column indices
_COL_TASK_ID = 0
_COL_TYPE = 1
_COL_DESC = 2
_COL_CATEGORY = 3
_COL_EXPECTED = 4
_COL_BEFORE = 5
_COL_AFTER = 6


def _format_value(value: float) -> str:
    """Format simulation value for display."""
    if value == 0.0:
        return "0"
    if abs(value) < 0.01:
        return f"{value:.2e}"
    if abs(value) >= 1000:
        return f"{value:.1f}"
    return f"{value:.4f}"


class TaskPanelWidget(QWidget):
    """Panel displaying metabolic task results before and after gap-filling."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._before_map: dict[str, TaskResult] = {}
        self._after_map: dict[str, TaskResult] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Summary label
        self._summary_label = QLabel("No task results available")
        self._summary_label.setObjectName("sectionTitle")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        # Category summary table
        cat_label = QLabel("Category Summary")
        cat_label.setStyleSheet(f"font-weight: bold; color: {THEME.text};")
        layout.addWidget(cat_label)

        self._category_table = QTableWidget()
        self._category_table.setColumnCount(4)
        self._category_table.setHorizontalHeaderLabels(
            ["Category", "Before (pass/total)", "After (pass/total)", "Fixed"]
        )
        self._category_table.horizontalHeader().setStretchLastSection(True)
        self._category_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._category_table.verticalHeader().setVisible(False)
        self._category_table.setAlternatingRowColors(True)
        self._category_table.setMaximumHeight(200)
        layout.addWidget(self._category_table)

        # Hint label
        hint_label = QLabel("Double-click a row to view task details")
        hint_label.setStyleSheet(f"color: {THEME.muted_text}; font-style: italic;")
        layout.addWidget(hint_label)

        # Detail table
        detail_label = QLabel("Task Details")
        detail_label.setStyleSheet(f"font-weight: bold; color: {THEME.text};")
        layout.addWidget(detail_label)

        self._detail_table = QTableWidget()
        self._detail_table.setColumnCount(7)
        self._detail_table.setHorizontalHeaderLabels(
            ["Task ID", "Type", "Description", "Category", "Expected", "Before", "After"]
        )
        header = self._detail_table.horizontalHeader()
        header.setSectionResizeMode(_COL_TASK_ID, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_DESC, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_EXPECTED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_BEFORE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_AFTER, QHeaderView.ResizeMode.ResizeToContents)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.cellDoubleClicked.connect(self._on_detail_double_clicked)
        layout.addWidget(self._detail_table)

    def set_results(
        self,
        before: list[TaskResult],
        after: list[TaskResult] | None = None,
    ) -> None:
        """Populate the panel with task results."""
        self._before_map = {r.task.task_id: r for r in before}
        self._after_map = (
            {r.task.task_id: r for r in after} if after else {}
        )

        # Compute summary
        total = len(before)
        before_pass = sum(1 for r in before if r.passed)
        after_pass = sum(1 for r in after if r.passed) if after else 0
        fixed = 0
        if after:
            for task_id, br in self._before_map.items():
                ar = self._after_map.get(task_id)
                if ar and not br.passed and ar.passed:
                    fixed += 1

        if after:
            self._summary_label.setText(
                f"{before_pass}/{total} passed (before)  ->  "
                f"{after_pass}/{total} passed (after),  {fixed} tasks fixed"
            )
        else:
            self._summary_label.setText(f"{before_pass}/{total} tasks passed")

        # Build category summary
        self._build_category_table(before, after, self._before_map, self._after_map)

        # Build detail table
        self._build_detail_table(before, self._before_map, self._after_map)

    def _build_category_table(
        self,
        before: list[TaskResult],
        after: list[TaskResult] | None,
        before_map: dict[str, TaskResult],
        after_map: dict[str, TaskResult],
    ) -> None:
        categories: dict[str, dict] = {}
        for r in before:
            cat = r.task.category or "Uncategorized"
            if cat not in categories:
                categories[cat] = {
                    "before_pass": 0,
                    "before_total": 0,
                    "after_pass": 0,
                    "after_total": 0,
                    "fixed": 0,
                }
            categories[cat]["before_total"] += 1
            if r.passed:
                categories[cat]["before_pass"] += 1

        if after:
            for r in after:
                cat = r.task.category or "Uncategorized"
                if cat in categories:
                    categories[cat]["after_total"] += 1
                    if r.passed:
                        categories[cat]["after_pass"] += 1
                    # Check if fixed
                    br = before_map.get(r.task.task_id)
                    if br and not br.passed and r.passed:
                        categories[cat]["fixed"] += 1

        self._category_table.setRowCount(len(categories))
        for row, (cat, data) in enumerate(sorted(categories.items())):
            self._category_table.setItem(row, 0, QTableWidgetItem(cat))
            self._category_table.setItem(
                row, 1,
                QTableWidgetItem(f"{data['before_pass']}/{data['before_total']}"),
            )
            if after:
                self._category_table.setItem(
                    row, 2,
                    QTableWidgetItem(f"{data['after_pass']}/{data['after_total']}"),
                )
                fixed_item = QTableWidgetItem(str(data["fixed"]))
                if data["fixed"] > 0:
                    fixed_item.setForeground(QColor(_COLOR_FAIL_PASS))
                self._category_table.setItem(row, 3, fixed_item)
            else:
                self._category_table.setItem(row, 2, QTableWidgetItem("-"))
                self._category_table.setItem(row, 3, QTableWidgetItem("-"))

    def _build_detail_table(
        self,
        before: list[TaskResult],
        before_map: dict[str, TaskResult],
        after_map: dict[str, TaskResult],
    ) -> None:
        self._detail_table.setRowCount(len(before))
        for row, br in enumerate(before):
            task = br.task
            ar = after_map.get(task.task_id)

            # Task ID
            self._detail_table.setItem(row, _COL_TASK_ID, QTableWidgetItem(task.task_id))

            # Type
            self._detail_table.setItem(row, _COL_TYPE, QTableWidgetItem(task.task_type))

            # Description
            desc = task.description or f"{task.task_type}: {task.target_id}"
            self._detail_table.setItem(row, _COL_DESC, QTableWidgetItem(desc))

            # Category
            self._detail_table.setItem(
                row, _COL_CATEGORY, QTableWidgetItem(task.category or "Uncategorized")
            )

            # Expected condition
            expected_text = f"{task.expected_operator}{task.expected_value:g}"
            expected_item = QTableWidgetItem(expected_text)
            expected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._detail_table.setItem(row, _COL_EXPECTED, expected_item)

            # Before status with actual value
            icon = "\u2705" if br.passed else "\u274c"
            val = _format_value(br.actual_value)
            before_item = QTableWidgetItem(f"{icon} {val}")
            before_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._detail_table.setItem(row, _COL_BEFORE, before_item)

            # After status with actual value
            if ar is not None:
                icon = "\u2705" if ar.passed else "\u274c"
                val = _format_value(ar.actual_value)
                after_item = QTableWidgetItem(f"{icon} {val}")
                after_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color coding based on transition
                color = self._transition_color(br.passed, ar.passed)
                after_item.setForeground(QColor(color))
                before_item.setForeground(QColor(color))
                self._detail_table.setItem(row, _COL_AFTER, after_item)
            else:
                self._detail_table.setItem(row, _COL_AFTER, QTableWidgetItem("-"))

    def _on_detail_double_clicked(self, row: int, _col: int) -> None:
        """Open task detail dialog on row double-click."""
        task_id_item = self._detail_table.item(row, _COL_TASK_ID)
        if not task_id_item:
            return
        task_id = task_id_item.text()
        before_result = self._before_map.get(task_id)
        if not before_result:
            return
        after_result = self._after_map.get(task_id)

        from src.gui.task_detail_dialog import TaskDetailDialog

        dialog = TaskDetailDialog(before_result, after_result, parent=self)
        dialog.exec()

    @staticmethod
    def _transition_color(before_passed: bool, after_passed: bool) -> str:
        if before_passed and after_passed:
            return _COLOR_PASS_PASS
        elif not before_passed and after_passed:
            return _COLOR_FAIL_PASS
        elif not before_passed and not after_passed:
            return _COLOR_FAIL_FAIL
        else:
            return _COLOR_PASS_FAIL

    def clear(self) -> None:
        self._summary_label.setText("No task results available")
        self._category_table.setRowCount(0)
        self._detail_table.setRowCount(0)
        self._before_map.clear()
        self._after_map.clear()
