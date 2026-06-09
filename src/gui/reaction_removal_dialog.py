"""Reaction removal dialog with task impact preview."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.models import Reaction, TaskResult
from src.gui.theme import THEME

if TYPE_CHECKING:
    import cobra

    from src.core.models import MetabolicTask

logger = logging.getLogger("metataskgapfill.gui.reaction_removal")

# Transition colors
_COLOR_PASS_FAIL = "#e74c3c"  # red: regression
_COLOR_FAIL_PASS = "#3498db"  # blue: improvement


def _safe_emit(signal, *args) -> None:
    with suppress(RuntimeError):
        signal.emit(*args)


class _TaskSimSignals(QObject):
    finished = Signal(list)  # list[TaskResult]
    error = Signal(str)


class TaskSimulationWorker(QRunnable):
    """Run tasks on a model copy with the target reaction removed."""

    def __init__(
        self,
        cobra_model: cobra.Model | None,
        reaction_id: str,
        tasks: list[MetabolicTask],
    ) -> None:
        super().__init__()
        self.signals = _TaskSimSignals()
        self._cobra_model = cobra_model
        self._reaction_id = reaction_id
        self._tasks = tasks
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            from src.core.task_parser import TaskRunner

            test_model = self._cobra_model.copy()
            rxn = test_model.reactions.get_by_id(self._reaction_id)
            test_model.remove_reactions([rxn], remove_orphans=True)
            runner = TaskRunner()
            results = runner.run_all(test_model, self._tasks)
            _safe_emit(self.signals.finished, results)
        except Exception as e:
            logger.error("Task simulation error: %s", e)
            _safe_emit(self.signals.error, str(e))


class ReactionRemovalDialog(QDialog):
    """Dialog showing task impact preview before reaction removal."""

    def __init__(
        self,
        reaction: Reaction,
        cobra_model: cobra.Model,
        tasks: list[MetabolicTask],
        current_results: list[TaskResult],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._reaction = reaction
        self._cobra_model = cobra_model
        self._tasks = tasks
        self._current_results = current_results
        self._current_map = {r.task.task_id: r for r in current_results}
        self._setup_ui()
        self._start_simulation()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Remove Reaction: {self._reaction.id}")
        self.setMinimumSize(550, 450)
        layout = QVBoxLayout(self)

        # Title
        title = QLabel(f"Remove: {self._reaction.id} ({self._reaction.name})")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {THEME.text};")
        layout.addWidget(title)

        # Progress bar (shown during simulation)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setTextVisible(True)
        self._progress.setFormat("Analyzing task impact...")
        layout.addWidget(self._progress)

        # Summary label (hidden until simulation completes)
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setVisible(False)
        layout.addWidget(self._summary_label)

        # Affected tasks table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Task ID", "Category", "Before", "After"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setVisible(False)
        layout.addWidget(self._table)

        # Warning label
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setVisible(False)
        layout.addWidget(self._warning_label)

        # Buttons
        self._buttons = QDialogButtonBox()
        self._cancel_btn = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._remove_btn = self._buttons.addButton("Remove Reaction", QDialogButtonBox.ButtonRole.AcceptRole)
        self._remove_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #e74c3c; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self._remove_btn.setEnabled(False)
        self._buttons.rejected.connect(self.reject)
        self._buttons.accepted.connect(self.accept)
        layout.addWidget(self._buttons)

    def _start_simulation(self) -> None:
        if self._cobra_model is None or not self._tasks:
            self._progress.setVisible(False)
            self._summary_label.setText("Task impact analysis is unavailable.")
            self._summary_label.setVisible(True)
            return

        worker = TaskSimulationWorker(
            self._cobra_model, self._reaction.id, self._tasks
        )
        worker.signals.finished.connect(self._on_simulation_done)
        worker.signals.error.connect(self._on_simulation_error)
        QThreadPool.globalInstance().start(worker)

    def _on_simulation_done(self, after_results: list[TaskResult]) -> None:
        self._progress.setVisible(False)

        after_map = {r.task.task_id: r for r in after_results}
        before_pass = sum(1 for r in self._current_results if r.passed)
        after_pass = sum(1 for r in after_results if r.passed)
        total = len(self._current_results)
        diff = after_pass - before_pass

        # Summary
        diff_text = f"+{diff}" if diff > 0 else str(diff)
        self._summary_label.setText(
            f"Before: {before_pass}/{total} tasks passed\n"
            f"After:  {after_pass}/{total} tasks passed\n"
            f"Change: {diff_text} tasks"
        )
        self._summary_label.setStyleSheet(f"font-size: 13px; color: {THEME.text}; padding: 8px;")
        self._summary_label.setVisible(True)

        # Build affected tasks table (only changed ones)
        changed: list[tuple[str, str, bool, bool]] = []
        for task_id, br in self._current_map.items():
            ar = after_map.get(task_id)
            if ar and br.passed != ar.passed:
                cat = br.task.category or "Uncategorized"
                changed.append((task_id, cat, br.passed, ar.passed))

        if changed:
            self._table.setRowCount(len(changed))
            for row, (task_id, cat, before_ok, after_ok) in enumerate(changed):
                self._table.setItem(row, 0, QTableWidgetItem(task_id))
                self._table.setItem(row, 1, QTableWidgetItem(cat))

                before_item = QTableWidgetItem("PASS" if before_ok else "FAIL")
                before_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 2, before_item)

                after_item = QTableWidgetItem("PASS" if after_ok else "FAIL")
                after_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                color = _COLOR_FAIL_PASS if after_ok else _COLOR_PASS_FAIL
                after_item.setForeground(QColor(color))
                before_item.setForeground(QColor(color))
                self._table.setItem(row, 3, after_item)

            self._table.setVisible(True)

        # Warning label
        regressions = sum(1 for _, _, b, a in changed if b and not a)
        improvements = sum(1 for _, _, b, a in changed if not b and a)
        if regressions == 0 and improvements == 0:
            self._warning_label.setText("No task impact detected.")
            self._warning_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 4px;")
        elif regressions == 0 and improvements > 0:
            self._warning_label.setText(f"{improvements} task(s) will improve after removal.")
            self._warning_label.setStyleSheet("color: #3498db; font-weight: bold; padding: 4px;")
        elif regressions <= 3:
            self._warning_label.setText(f"{regressions} task(s) will fail after removal.")
            self._warning_label.setStyleSheet("color: #f39c12; font-weight: bold; padding: 4px;")
        else:
            self._warning_label.setText(f"{regressions} tasks will fail — significant model impact!")
            self._warning_label.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 4px;")
        self._warning_label.setVisible(True)

        self._remove_btn.setEnabled(True)

    def _on_simulation_error(self, error_msg: str) -> None:
        self._progress.setVisible(False)
        self._summary_label.setText(f"Simulation error: {error_msg}")
        self._summary_label.setStyleSheet("color: #e74c3c; padding: 8px;")
        self._summary_label.setVisible(True)
        # Keep remove button disabled on error
