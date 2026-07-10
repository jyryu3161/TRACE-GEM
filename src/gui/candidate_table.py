"""Candidate reaction table model and view for gap-filling."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.core.models import CandidateReaction, EvidenceTier, ReactionEvidence


class CandidateTableModel(QAbstractTableModel):
    """Table model for candidate reactions from universal model."""

    COLUMNS = [
        "ID",
        "Name",
        "Equation",
        "Subsystem",
        "Organism",
        "Evidence",
        "Penalty",
        "KEGG IDs",
        "GPR",
        "Selected",
    ]
    COL_ID = 0
    COL_NAME = 1
    COL_EQUATION = 2
    COL_SUBSYSTEM = 3
    COL_ORGANISM = 4
    COL_SCORE = 5
    COL_PENALTY = 6
    COL_KEGG = 7
    COL_GPR = 8
    COL_SELECTED = 9

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._candidates: list[CandidateReaction] = []
        self._evidence: dict[str, ReactionEvidence] = {}

    def set_candidates(self, candidates: list[CandidateReaction]) -> None:
        self.beginResetModel()
        self._candidates = list(candidates)
        self.endResetModel()

    def set_evidence(self, evidence: dict[str, ReactionEvidence]) -> None:
        self._evidence = evidence
        self.beginResetModel()
        self.endResetModel()

    def get_candidate(self, row: int) -> CandidateReaction | None:
        if 0 <= row < len(self._candidates):
            return self._candidates[row]
        return None

    def get_selected_candidates(self) -> list[CandidateReaction]:
        return [c for c in self._candidates if c.selected]

    def get_evidence(self, reaction_id: str) -> ReactionEvidence | None:
        """Get evidence for a specific reaction."""
        return self._evidence.get(reaction_id)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._candidates)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.column() == self.COL_SELECTED:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None

        candidate = self._candidates[index.row()]
        rxn = candidate.reaction
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ID:
                return rxn.id
            elif col == self.COL_NAME:
                return rxn.name
            elif col == self.COL_EQUATION:
                eq = rxn.equation_id or rxn.equation
                return eq if len(eq) <= 60 else eq[:57] + "..."
            elif col == self.COL_SUBSYSTEM:
                return rxn.subsystem or ""
            elif col == self.COL_ORGANISM:
                if candidate.organism_exists is True:
                    return "\u2705"  # check mark
                elif candidate.organism_exists is False:
                    return "\u274c"  # cross mark
                return "\u2753"  # question mark
            elif col == self.COL_SCORE:
                ev = self._evidence.get(rxn.id)
                if ev:
                    return ev.evidence_tier.label
                return ""
            elif col == self.COL_PENALTY:
                return f"{candidate.penalty:.1f}"
            elif col == self.COL_KEGG:
                ev = self._evidence.get(rxn.id)
                if ev and ev.kegg_reaction_ids:
                    return ", ".join(ev.kegg_reaction_ids)
                return ""
            elif col == self.COL_GPR:
                gpr = candidate.assigned_gpr
                return gpr if len(gpr) <= 50 else gpr[:47] + "..."
            elif col == self.COL_SELECTED:
                return None  # Handled by CheckStateRole

        elif role == Qt.ItemDataRole.CheckStateRole:
            if col == self.COL_SELECTED:
                return Qt.CheckState.Checked if candidate.selected else Qt.CheckState.Unchecked

        elif role == Qt.ItemDataRole.UserRole:
            if col == self.COL_SCORE:
                ev = self._evidence.get(rxn.id)
                return ev.evidence_tier.rank if ev else 0
            elif col == self.COL_PENALTY:
                return candidate.penalty
            elif col == self.COL_ORGANISM:
                if candidate.organism_exists is True:
                    return 2
                elif candidate.organism_exists is None:
                    return 1
                return 0

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_GPR:
                return candidate.assigned_gpr
            elif col == self.COL_EQUATION:
                return rxn.equation_id or rxn.equation

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # type: ignore[override]
        if not index.isValid():
            return False

        if role == Qt.ItemDataRole.CheckStateRole and index.column() == self.COL_SELECTED:
            candidate = self._candidates[index.row()]
            candidate.selected = value == Qt.CheckState.Checked.value
            self.dataChanged.emit(index, index)
            return True

        return False

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        if column == self.COL_SCORE:
            self._candidates.sort(
                key=lambda c: (
                    self._evidence.get(
                        c.reaction.id, ReactionEvidence(c.reaction.id)
                    ).evidence_tier.rank
                ),
                reverse=reverse,
            )
        elif column == self.COL_PENALTY:
            self._candidates.sort(key=lambda c: c.penalty, reverse=reverse)
        elif column == self.COL_ID:
            self._candidates.sort(key=lambda c: c.reaction.id, reverse=reverse)
        elif column == self.COL_NAME:
            self._candidates.sort(key=lambda c: c.reaction.name, reverse=reverse)
        elif column == self.COL_SUBSYSTEM:
            self._candidates.sort(key=lambda c: c.reaction.subsystem or "", reverse=reverse)
        elif column == self.COL_ORGANISM:
            self._candidates.sort(
                key=lambda c: (
                    2 if c.organism_exists is True else (1 if c.organism_exists is None else 0)
                ),
                reverse=reverse,
            )

        self.endResetModel()


class CandidateFilterProxy(QSortFilterProxyModel):
    """Filter proxy for candidate table."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text_filter = ""
        self._organism_filter = ""  # "", "yes", "no", "unknown"
        self._min_tier_rank = 0
        self._subsystem_filter = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_text_filter(self, text: str) -> None:
        self._text_filter = text.lower()
        self.invalidateFilter()

    def set_organism_filter(self, value: str) -> None:
        self._organism_filter = value
        self.invalidateFilter()

    def set_min_tier(self, tier: EvidenceTier | None) -> None:
        self._min_tier_rank = tier.rank if tier else 0
        self.invalidateFilter()

    def set_subsystem_filter(self, subsystem: str) -> None:
        self._subsystem_filter = subsystem
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # type: ignore[override]
        model = self.sourceModel()
        if not isinstance(model, CandidateTableModel):
            return True

        candidate = model.get_candidate(source_row)
        if candidate is None:
            return False

        rxn = candidate.reaction

        # Text filter
        if self._text_filter:
            text = self._text_filter
            if (
                text not in rxn.id.lower()
                and text not in rxn.name.lower()
                and text not in candidate.assigned_gpr.lower()
            ):
                return False

        # Organism filter
        if self._organism_filter == "yes" and candidate.organism_exists is not True:
            return False
        if self._organism_filter == "no" and candidate.organism_exists is not False:
            return False
        if self._organism_filter == "unknown" and candidate.organism_exists is not None:
            return False

        # Subsystem filter
        if self._subsystem_filter and (rxn.subsystem or "") != self._subsystem_filter:
            return False

        # Evidence tier filter
        if self._min_tier_rank:
            ev = model.get_evidence(rxn.id)
            rank = ev.evidence_tier.rank if ev else 0
            if rank < self._min_tier_rank:
                return False

        return True


class CandidateTableWidget(QWidget):
    """Complete candidate reaction table widget with filters."""

    candidate_selected = Signal(str)  # reaction_id
    evaluate_requested = Signal(list)  # list[CandidateReaction]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = "default"  # "default" | "browse"
        self._model = CandidateTableModel()
        self._proxy = CandidateFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._overview_label: QLabel | None = None
        self._evaluate_btn: QPushButton | None = None
        self._setup_ui()

    def set_mode(self, mode: str) -> None:
        """Set widget mode: 'default' (gap-fill candidates) or 'browse' (universal)."""
        self._mode = mode
        if self._overview_label:
            self._overview_label.setVisible(mode == "browse")
        if self._evaluate_btn:
            self._evaluate_btn.setVisible(mode == "browse")

    def set_overview(self, text: str) -> None:
        """Set overview header text (browse mode)."""
        if self._overview_label:
            self._overview_label.setText(text)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Overview header (browse mode only, hidden by default)
        self._overview_label = QLabel()
        self._overview_label.setObjectName("sectionTitle")
        self._overview_label.setWordWrap(True)
        self._overview_label.setVisible(False)
        layout.addWidget(self._overview_label)

        # Filter bar
        filter_layout = QHBoxLayout()

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search candidates (ID, name, GPR)...")
        self._search.textChanged.connect(self._proxy.set_text_filter)
        filter_layout.addWidget(self._search, stretch=2)

        # Organism filter
        filter_layout.addWidget(QLabel("Organism:"))
        self._organism_combo = QComboBox()
        self._organism_combo.addItem("All", "")
        self._organism_combo.addItem("Yes", "yes")
        self._organism_combo.addItem("No", "no")
        self._organism_combo.addItem("Unknown", "unknown")
        self._organism_combo.currentIndexChanged.connect(self._on_organism_changed)
        filter_layout.addWidget(self._organism_combo)

        # Subsystem filter — hidden: universal model lacks subsystem info
        # (BiGG universal JSON has 0% coverage). Wired up for future revival.
        self._subsystem_combo = QComboBox()
        self._subsystem_combo.addItem("All Subsystems", "")
        self._subsystem_combo.currentIndexChanged.connect(self._on_subsystem_changed)
        self._subsystem_combo.setVisible(False)
        filter_layout.addWidget(self._subsystem_combo, stretch=1)

        filter_layout.addWidget(QLabel("Evidence:"))
        self._evidence_combo = QComboBox()
        self._evidence_combo.addItem("All", None)
        self._evidence_combo.addItem("High+", EvidenceTier.HIGH)
        self._evidence_combo.addItem("Moderate+", EvidenceTier.MODERATE)
        self._evidence_combo.addItem("Low+", EvidenceTier.LOW)
        self._evidence_combo.setToolTip("Minimum evidence tier filter")
        self._evidence_combo.currentIndexChanged.connect(self._on_evidence_filter_changed)
        filter_layout.addWidget(self._evidence_combo)

        layout.addLayout(filter_layout)

        # Evaluate button (browse mode only, hidden by default)
        eval_layout = QHBoxLayout()
        eval_layout.addStretch()
        self._evaluate_btn = QPushButton("Evaluate Selected")
        self._evaluate_btn.setVisible(False)
        self._evaluate_btn.clicked.connect(self._on_evaluate_clicked)
        eval_layout.addWidget(self._evaluate_btn)
        layout.addLayout(eval_layout)

        # Table view
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultSectionSize(90)
        header.resizeSection(CandidateTableModel.COL_ID, 100)
        header.resizeSection(CandidateTableModel.COL_NAME, 140)
        header.resizeSection(CandidateTableModel.COL_EQUATION, 180)
        header.resizeSection(CandidateTableModel.COL_SUBSYSTEM, 120)
        header.setSectionHidden(CandidateTableModel.COL_SUBSYSTEM, True)
        header.resizeSection(CandidateTableModel.COL_ORGANISM, 76)
        header.resizeSection(CandidateTableModel.COL_SCORE, 90)
        header.resizeSection(CandidateTableModel.COL_PENALTY, 70)
        header.resizeSection(CandidateTableModel.COL_KEGG, 100)
        header.resizeSection(CandidateTableModel.COL_GPR, 120)
        header.resizeSection(CandidateTableModel.COL_SELECTED, 60)

        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._table)

    def set_candidates(
        self,
        candidates: list[CandidateReaction],
        evidence: dict[str, ReactionEvidence] | None = None,
    ) -> None:
        self._model.set_candidates(candidates)
        if evidence:
            self._model.set_evidence(evidence)

        # Populate subsystem filter
        self._subsystem_combo.clear()
        self._subsystem_combo.addItem("All Subsystems", "")
        subsystems = sorted({c.reaction.subsystem for c in candidates if c.reaction.subsystem})
        for sub in subsystems:
            self._subsystem_combo.addItem(sub, sub)

        # Default sort by evidence tier descending
        self._table.sortByColumn(CandidateTableModel.COL_SCORE, Qt.SortOrder.DescendingOrder)

    def update_evidence(self, evidence: dict[str, ReactionEvidence]) -> None:
        self._model.set_evidence(evidence)

    def set_score_delegate(self, delegate: Any) -> None:
        self._table.setItemDelegateForColumn(CandidateTableModel.COL_SCORE, delegate)

    def get_candidates(self) -> list[CandidateReaction]:
        """Return all loaded candidates, or empty list if none."""
        return list(self._model._candidates)

    def get_selected_candidates(self) -> list[CandidateReaction]:
        return self._model.get_selected_candidates()

    def _on_organism_changed(self, _index: int) -> None:
        value = self._organism_combo.currentData() or ""
        self._proxy.set_organism_filter(value)

    def _on_subsystem_changed(self, _index: int) -> None:
        sub = self._subsystem_combo.currentData() or ""
        self._proxy.set_subsystem_filter(sub)

    def _on_evidence_filter_changed(self, _index: int) -> None:
        self._proxy.set_min_tier(self._evidence_combo.currentData())

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            source_index = self._proxy.mapToSource(current)
            candidate = self._model.get_candidate(source_index.row())
            if candidate:
                self.candidate_selected.emit(candidate.reaction.id)

    def _on_evaluate_clicked(self) -> None:
        selected = self._model.get_selected_candidates()
        if selected:
            self.evaluate_requested.emit(selected)
