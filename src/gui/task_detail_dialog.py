"""Dialog showing detailed information about a metabolic task result."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.models import TaskResult
from src.gui.theme import THEME


def _format_value(value: float) -> str:
    """Format simulation value for display."""
    if value == 0.0:
        return "0"
    if abs(value) < 0.01:
        return f"{value:.2e}"
    if abs(value) >= 1000:
        return f"{value:.1f}"
    return f"{value:.6f}"


class TaskDetailDialog(QDialog):
    """Dialog showing full details of a metabolic task and its simulation result."""

    def __init__(
        self,
        before: TaskResult,
        after: TaskResult | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._before = before
        self._after = after
        self._task = before.task
        self.setWindowTitle(f"Task Detail: {self._task.task_id}")
        self.setMinimumSize(550, 480)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Task Info ---
        info_group = QGroupBox("Task Info")
        info_form = QFormLayout(info_group)
        info_form.addRow("Task ID:", QLabel(self._task.task_id))
        info_form.addRow("Type:", QLabel(self._task.task_type))
        info_form.addRow("Target:", QLabel(self._task.target_id))
        info_form.addRow(
            "Description:",
            QLabel(self._task.description or "-"),
        )
        info_form.addRow("Category:", QLabel(self._task.category or "Uncategorized"))
        layout.addWidget(info_group)

        # --- Objective Function ---
        obj_group = QGroupBox("Objective Function")
        obj_layout = QVBoxLayout(obj_group)
        if self._task.task_type == "Metabolite":
            obj_text = (
                f"Maximize DM_{self._task.target_id}  (demand reaction for {self._task.target_id})"
            )
        else:
            obj_text = f"Maximize {self._task.target_id} flux"
        obj_label = QLabel(obj_text)
        obj_label.setWordWrap(True)
        obj_layout.addWidget(obj_label)
        layout.addWidget(obj_group)

        # --- Medium ---
        med_group = QGroupBox("Medium")
        med_layout = QVBoxLayout(med_group)
        if self._task.medium:
            med_table = QTableWidget()
            med_table.setColumnCount(2)
            med_table.setHorizontalHeaderLabels(["Exchange Reaction", "Lower Bound"])
            med_table.horizontalHeader().setStretchLastSection(True)
            med_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            med_table.verticalHeader().setVisible(False)
            med_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

            sorted_medium = sorted(self._task.medium.items())
            med_table.setRowCount(len(sorted_medium))
            for row, (rxn_id, bound) in enumerate(sorted_medium):
                med_table.setItem(row, 0, QTableWidgetItem(rxn_id))
                bound_item = QTableWidgetItem(f"{bound:g}")
                bound_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                med_table.setItem(row, 1, bound_item)

            med_table.setMaximumHeight(30 + 24 * min(len(sorted_medium), 8))
            med_layout.addWidget(med_table)
        else:
            med_layout.addWidget(QLabel("Default (no medium changes)"))
        layout.addWidget(med_group)

        # --- Constraints ---
        con_group = QGroupBox("Additional Constraints")
        con_layout = QVBoxLayout(con_group)
        if self._task.constraints:
            con_table = QTableWidget()
            con_table.setColumnCount(3)
            con_table.setHorizontalHeaderLabels(["Reaction", "Lower Bound", "Upper Bound"])
            con_table.horizontalHeader().setStretchLastSection(True)
            con_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            con_table.verticalHeader().setVisible(False)
            con_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

            sorted_constraints = sorted(self._task.constraints.items())
            con_table.setRowCount(len(sorted_constraints))
            for row, (rxn_id, (lower, upper)) in enumerate(sorted_constraints):
                con_table.setItem(row, 0, QTableWidgetItem(rxn_id))
                lower_item = QTableWidgetItem(f"{lower:g}")
                lower_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                con_table.setItem(row, 1, lower_item)
                upper_item = QTableWidgetItem(f"{upper:g}")
                upper_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                con_table.setItem(row, 2, upper_item)

            con_table.setMaximumHeight(30 + 24 * min(len(sorted_constraints), 6))
            con_layout.addWidget(con_table)
        else:
            con_layout.addWidget(QLabel("No additional constraints"))
        layout.addWidget(con_group)

        # --- Result ---
        result_group = QGroupBox("Result")
        result_form = QFormLayout(result_group)

        expected_text = f"{self._task.expected_operator}{self._task.expected_value:g}"
        result_form.addRow("Expected:", QLabel(expected_text))

        # Before result
        before_label = self._make_result_label(self._before)
        result_form.addRow("Before:", before_label)

        # After result
        if self._after is not None:
            after_label = self._make_result_label(self._after)

            # Apply transition color
            color = self._transition_color(self._before.passed, self._after.passed)
            before_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            after_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            result_form.addRow("After:", after_label)

        # Error message
        error_msg = self._before.error_message or (
            self._after.error_message if self._after else None
        )
        if error_msg:
            error_label = QLabel(error_msg)
            error_label.setWordWrap(True)
            error_label.setStyleSheet(f"color: {THEME.error};")
            result_form.addRow("Error:", error_label)

        layout.addWidget(result_group)

        # --- Close button ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _make_result_label(result: TaskResult) -> QLabel:
        """Create a label showing pass/fail status and actual value."""
        icon = "\u2705 PASS" if result.passed else "\u274c FAIL"
        val = _format_value(result.actual_value)
        label = QLabel(f"{icon}  (actual: {val})")
        return label

    @staticmethod
    def _transition_color(before_passed: bool, after_passed: bool) -> str:
        if before_passed and after_passed:
            return "#27ae60"
        elif not before_passed and after_passed:
            return "#3498db"
        elif not before_passed and not after_passed:
            return "#e74c3c"
        else:
            return "#e67e22"
