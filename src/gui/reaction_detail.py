"""Reaction detail panel showing equation, GPR, bounds, cross-references."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelData, Reaction, ReactionEvidence
from src.gui.theme import THEME

logger = logging.getLogger("metataskgapfill.gui.reaction_detail")


class ReactionDetailWidget(QWidget):
    """Shows detailed information about a selected reaction."""

    reaction_modified = Signal(str)  # reaction_id
    removal_requested = Signal(str)  # reaction_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._reaction: Reaction | None = None
        self._model: ModelData | None = None
        self._read_only = False
        self._displayed_bounds: tuple[float, float] | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Title (outside scroll area)
        self._title = QLabel("Select a reaction")
        self._title.setObjectName("sectionTitle")
        outer.addWidget(self._title)

        # Scroll area wrapping all content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 4, 0)

        # Info group
        info_group = QGroupBox("Reaction Info")
        info_form = QFormLayout(info_group)
        info_form.setVerticalSpacing(10)
        info_form.setContentsMargins(12, 24, 12, 12)

        self._id_label = QLabel("-")
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Reaction name")
        self._subsystem_edit = QLineEdit()
        self._subsystem_edit.setPlaceholderText("Subsystem")

        # Bounds
        bounds_layout = QHBoxLayout()
        self._lower_bound_spin = QDoubleSpinBox()
        self._lower_bound_spin.setDecimals(15)
        self._lower_bound_spin.setRange(float("-inf"), float("inf"))
        self._lower_bound_spin.setPrefix("lower: ")
        self._upper_bound_spin = QDoubleSpinBox()
        self._upper_bound_spin.setDecimals(15)
        self._upper_bound_spin.setRange(float("-inf"), float("inf"))
        self._upper_bound_spin.setPrefix("upper: ")
        bounds_layout.addWidget(self._lower_bound_spin)
        bounds_layout.addWidget(self._upper_bound_spin)

        info_form.addRow("ID:", self._id_label)
        info_form.addRow("Name:", self._name_edit)
        info_form.addRow("Subsystem:", self._subsystem_edit)
        info_form.addRow("Bounds:", bounds_layout)

        layout.addWidget(info_group)

        # Equation (ID)
        eq_id_group = QGroupBox("Equation (ID)")
        eq_id_layout = QVBoxLayout(eq_id_group)
        self._equation_id_display = QTextEdit()
        self._equation_id_display.setMinimumHeight(60)
        self._equation_id_display.setMaximumHeight(80)
        self._equation_id_display.setReadOnly(True)
        eq_id_layout.addWidget(self._equation_id_display)
        layout.addWidget(eq_id_group)

        # Equation (Name)
        eq_group = QGroupBox("Equation (Name)")
        eq_layout = QVBoxLayout(eq_group)
        self._equation_edit = QTextEdit()
        self._equation_edit.setMinimumHeight(60)
        self._equation_edit.setMaximumHeight(80)
        eq_layout.addWidget(self._equation_edit)
        layout.addWidget(eq_group)

        # GPR
        gpr_group = QGroupBox("Gene-Protein-Reaction Rule")
        gpr_layout = QVBoxLayout(gpr_group)
        self._gpr_edit = QTextEdit()
        self._gpr_edit.setMinimumHeight(60)
        self._gpr_edit.setMaximumHeight(100)
        gpr_layout.addWidget(self._gpr_edit)
        layout.addWidget(gpr_group)

        # Cross-references
        xref_group = QGroupBox("Cross-References")
        xref_layout = QVBoxLayout(xref_group)
        self._xref_browser = QTextBrowser()
        self._xref_browser.setMinimumHeight(80)
        self._xref_browser.setMaximumHeight(150)
        self._xref_browser.setOpenExternalLinks(True)
        xref_layout.addWidget(self._xref_browser)
        layout.addWidget(xref_group)

        # Buttons
        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("Save Changes")
        self._save_btn.clicked.connect(self._save_changes)
        self._save_btn.setEnabled(False)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #e74c3c; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        self._remove_btn.setEnabled(False)

        btn_layout.addStretch()
        btn_layout.addWidget(self._remove_btn)
        btn_layout.addWidget(self._save_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def set_read_only(self, read_only: bool) -> None:
        """Toggle read-only mode for universal reactions."""
        self._read_only = read_only
        self._name_edit.setReadOnly(read_only)
        self._subsystem_edit.setReadOnly(read_only)
        self._lower_bound_spin.setReadOnly(read_only)
        self._upper_bound_spin.setReadOnly(read_only)
        self._equation_edit.setReadOnly(read_only)
        self._gpr_edit.setReadOnly(read_only)
        self._save_btn.setVisible(not read_only)
        self._remove_btn.setVisible(not read_only)

    def set_model(self, model: ModelData) -> None:
        """Store reference to ModelData (including cobra_model) for sync on save."""
        self._model = model

    def set_reaction(self, reaction: Reaction) -> None:
        self._reaction = reaction
        self._title.setText(f"Reaction: {reaction.id}")
        self._id_label.setText(reaction.id)
        self._name_edit.setText(reaction.name)
        self._subsystem_edit.setText(reaction.subsystem or "")
        self._lower_bound_spin.setValue(reaction.lower_bound)
        self._upper_bound_spin.setValue(reaction.upper_bound)
        self._displayed_bounds = (
            self._lower_bound_spin.value(),
            self._upper_bound_spin.value(),
        )
        self._equation_id_display.setPlainText(reaction.equation_id or reaction.equation)
        self._equation_edit.setPlainText(reaction.equation)
        self._gpr_edit.setPlainText(reaction.gene_reaction_rule or "")

        # Cross-references from annotation
        xref_lines = []
        for key, values in reaction.annotation.items():
            for v in values:
                xref_lines.append(f'<b style="color: {THEME.text};">{key}:</b> {v}')
        self._xref_browser.setHtml(
            f'<div style="color: {THEME.text};">{"<br>".join(xref_lines)}</div>'
            if xref_lines
            else f'<span style="color: {THEME.muted_text};">No annotations</span>'
        )

        self._save_btn.setEnabled(True)
        self._remove_btn.setEnabled(not self._read_only)

    def update_evidence(self, evidence: ReactionEvidence) -> None:
        if not evidence:
            return

        # Update cross-references with resolved IDs
        lines = []
        if evidence.ec_numbers:
            lines.append(f"<b>EC Numbers:</b> {', '.join(evidence.ec_numbers)}")
        if evidence.kegg_reaction_ids:
            for kid in evidence.kegg_reaction_ids:
                url = f"https://www.kegg.jp/entry/{kid}"
                lines.append(f'<b>KEGG:</b> <a href="{url}">{kid}</a>')

        # Show matching results
        if evidence.substrate_match_ratio > 0 or evidence.product_match_ratio > 0:
            lines.append(
                f"<b>Substrate match:</b> {evidence.substrate_match_ratio:.0%} | "
                f"<b>Product match:</b> {evidence.product_match_ratio:.0%}"
            )
        if lines:
            self._xref_browser.setHtml(
                f'<div style="color: {THEME.text};">{"<br>".join(lines)}</div>'
            )

    def clear(self) -> None:
        self._reaction = None
        self._displayed_bounds = None
        self._title.setText("Select a reaction")
        self._id_label.setText("-")
        self._name_edit.clear()
        self._subsystem_edit.clear()
        self._lower_bound_spin.setValue(-1000.0)
        self._upper_bound_spin.setValue(1000.0)
        self._equation_id_display.clear()
        self._equation_edit.clear()
        self._gpr_edit.clear()
        self._xref_browser.setHtml("")
        self._save_btn.setEnabled(False)
        self._remove_btn.setEnabled(False)

    def _on_remove_clicked(self) -> None:
        if self._reaction:
            self.removal_requested.emit(self._reaction.id)

    def _save_changes(self) -> None:
        if not self._reaction:
            return

        reaction = self._reaction

        name = self._name_edit.text()
        subsystem = self._subsystem_edit.text() or None
        gene_rule = self._gpr_edit.toPlainText()
        lb = self._lower_bound_spin.value()
        ub = self._upper_bound_spin.value()
        # Keep the exact original bounds when the user did not edit them, even
        # when their precision exceeds the editor's displayed decimal places.
        if self._displayed_bounds is not None:
            if lb == self._displayed_bounds[0]:
                lb = reaction.lower_bound
            if ub == self._displayed_bounds[1]:
                ub = reaction.upper_bound
        if lb > ub:
            lb, ub = ub, lb

        # Commit to the calculation model before changing the GUI model.
        if self._model and self._model.cobra_model:
            try:
                import cobra

                cm = self._model.cobra_model
                if isinstance(cm, cobra.Model):
                    cobra_rxn = cm.reactions.get_by_id(reaction.id)
                    original = (
                        cobra_rxn.bounds,
                        cobra_rxn.name,
                        cobra_rxn.gene_reaction_rule,
                        cobra_rxn.subsystem,
                    )
                    try:
                        cobra_rxn.bounds = (lb, ub)
                        cobra_rxn.gene_reaction_rule = gene_rule
                        cobra_rxn.name = name
                        cobra_rxn.subsystem = subsystem or ""
                    except Exception:
                        (
                            cobra_rxn.bounds,
                            cobra_rxn.name,
                            cobra_rxn.gene_reaction_rule,
                            cobra_rxn.subsystem,
                        ) = original
                        raise
            except Exception as e:
                logger.warning("Failed to sync cobra model for %s: %s", reaction.id, e)
                QMessageBox.warning(self, "Save Changes Error", str(e))
                return

        reaction.name = name
        reaction.subsystem = subsystem
        reaction.lower_bound = lb
        reaction.upper_bound = ub
        reaction.gene_reaction_rule = gene_rule
        self.set_reaction(reaction)
        self.reaction_modified.emit(reaction.id)
