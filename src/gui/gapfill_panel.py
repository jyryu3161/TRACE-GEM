"""Gap-filling results panel with added reactions and actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.core.models import GapFillResult


class GapFillPanelWidget(QWidget):
    """Panel displaying gap-filling results and action buttons."""

    apply_requested = Signal()
    export_sbml_requested = Signal()
    export_report_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Summary
        self._summary_label = QLabel("No gap-filling results")
        self._summary_label.setObjectName("sectionTitle")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        # Added reactions table
        rxn_group = QGroupBox("Added Reactions")
        rxn_layout = QVBoxLayout(rxn_group)

        self._reaction_table = QTableWidget()
        self._reaction_table.setColumnCount(5)
        self._reaction_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Score", "GPR", "Fixing Task"]
        )
        self._reaction_table.horizontalHeader().setStretchLastSection(True)
        self._reaction_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._reaction_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._reaction_table.verticalHeader().setVisible(False)
        self._reaction_table.setAlternatingRowColors(True)
        rxn_layout.addWidget(self._reaction_table)
        layout.addWidget(rxn_group)

        # Infeasible tasks section
        infeasible_group = QGroupBox("Infeasible Tasks")
        infeasible_layout = QVBoxLayout(infeasible_group)

        self._infeasible_browser = QTextBrowser()
        self._infeasible_browser.setMaximumHeight(120)
        self._infeasible_browser.setPlainText("None")
        infeasible_layout.addWidget(self._infeasible_browser)
        layout.addWidget(infeasible_group)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._apply_btn = QPushButton("Apply to Model")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self.apply_requested.emit)
        btn_layout.addWidget(self._apply_btn)

        self._export_sbml_btn = QPushButton("Export Improved SBML")
        self._export_sbml_btn.setEnabled(False)
        self._export_sbml_btn.clicked.connect(self.export_sbml_requested.emit)
        btn_layout.addWidget(self._export_sbml_btn)

        self._export_report_btn = QPushButton("Export Report")
        self._export_report_btn.setEnabled(False)
        self._export_report_btn.clicked.connect(self.export_report_requested.emit)
        btn_layout.addWidget(self._export_report_btn)

        layout.addLayout(btn_layout)

    def set_result(self, result: GapFillResult) -> None:
        """Populate the panel with gap-filling results."""
        # Summary
        added = len(result.added_reactions)
        self._summary_label.setText(
            f"Gap-filling complete: {added} reactions added, "
            f"{result.tasks_fixed}/{result.total_tasks} tasks fixed, "
            f"{result.iterations} iteration(s)"
        )

        # Added reactions table — sort by Score descending
        self._reaction_table.setSortingEnabled(False)
        self._reaction_table.setRowCount(added)
        for row, candidate in enumerate(result.added_reactions):
            rxn = candidate.reaction

            self._reaction_table.setItem(row, 0, QTableWidgetItem(rxn.id))
            self._reaction_table.setItem(row, 1, QTableWidgetItem(rxn.name))

            score_item = QTableWidgetItem()
            score_item.setData(Qt.ItemDataRole.DisplayRole, f"{candidate.penalty:.1f}")
            score_item.setData(Qt.ItemDataRole.UserRole, candidate.penalty)
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._reaction_table.setItem(row, 2, score_item)

            gpr = candidate.assigned_gpr or "-"
            self._reaction_table.setItem(row, 3, QTableWidgetItem(gpr))

            # Fixing task column left empty for now (populated by engine later)
            self._reaction_table.setItem(row, 4, QTableWidgetItem(""))

        self._reaction_table.setSortingEnabled(True)
        self._reaction_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

        # Infeasible tasks
        if result.infeasible_tasks:
            lines = [f"- {t}" for t in result.infeasible_tasks]
            self._infeasible_browser.setPlainText(
                f"{len(result.infeasible_tasks)} task(s) could not be fixed:\n"
                + "\n".join(lines)
            )
        else:
            self._infeasible_browser.setPlainText("None - all tasks resolved")

        # Enable buttons
        has_results = added > 0
        self._apply_btn.setEnabled(has_results)
        self._export_sbml_btn.setEnabled(has_results)
        self._export_report_btn.setEnabled(True)

    def set_partial_result(self, result: GapFillResult) -> None:
        """Display partial results from a cancelled workflow."""
        phase = result.completed_phase
        added = len(result.added_reactions)

        self._summary_label.setText(
            f"Partial result (Phase {phase}/5): {added} reactions added \u2014 "
            f"Resume available"
        )
        self._summary_label.setStyleSheet("color: #f0ad4e; font-weight: bold;")

        if result.added_reactions:
            self._reaction_table.setSortingEnabled(False)
            self._reaction_table.setRowCount(added)
            for row, candidate in enumerate(result.added_reactions):
                rxn = candidate.reaction
                self._reaction_table.setItem(row, 0, QTableWidgetItem(rxn.id))
                self._reaction_table.setItem(row, 1, QTableWidgetItem(rxn.name))

                score_item = QTableWidgetItem()
                score_item.setData(Qt.ItemDataRole.DisplayRole, f"{candidate.penalty:.1f}")
                score_item.setData(Qt.ItemDataRole.UserRole, candidate.penalty)
                score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._reaction_table.setItem(row, 2, score_item)

                gpr = candidate.assigned_gpr or "-"
                self._reaction_table.setItem(row, 3, QTableWidgetItem(gpr))
                self._reaction_table.setItem(row, 4, QTableWidgetItem(""))

            self._reaction_table.setSortingEnabled(True)
            self._reaction_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

        self._apply_btn.setEnabled(False)
        self._export_sbml_btn.setEnabled(False)
        self._export_report_btn.setEnabled(added > 0)

    def clear(self) -> None:
        self._summary_label.setText("No gap-filling results")
        self._summary_label.setStyleSheet("")
        self._reaction_table.setRowCount(0)
        self._infeasible_browser.setPlainText("None")
        self._apply_btn.setEnabled(False)
        self._export_sbml_btn.setEnabled(False)
        self._export_report_btn.setEnabled(False)
