"""Reaction table model and view."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelData, Reaction


class ReactionTableModel(QAbstractTableModel):
    """Table model for reactions list."""

    COLUMNS = ["ID", "Name", "Equation", "Subsystem", "Genes", "GPR"]
    COL_ID = 0
    COL_NAME = 1
    COL_EQUATION = 2
    COL_SUBSYSTEM = 3
    COL_GENES = 4
    COL_GPR = 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._reactions: list[Reaction] = []

    def set_reactions(self, reactions: list[Reaction]) -> None:
        self.beginResetModel()
        self._reactions = list(reactions)
        self.endResetModel()

    def get_reaction(self, row: int) -> Reaction | None:
        if 0 <= row < len(self._reactions):
            return self._reactions[row]
        return None

    @property
    def reactions(self) -> list[Reaction]:
        """Get list of all reactions."""
        return list(self._reactions)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._reactions)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None

        rxn = self._reactions[index.row()]
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
            elif col == self.COL_GENES:
                return str(len(rxn.genes))
            elif col == self.COL_GPR:
                gpr = rxn.gene_reaction_rule
                return gpr if len(gpr) <= 50 else gpr[:47] + "..."

        elif role == Qt.ItemDataRole.UserRole:
            if col == self.COL_GENES:
                return len(rxn.genes)

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_GPR:
                return rxn.gene_reaction_rule
            elif col == self.COL_EQUATION:
                return rxn.equation_id or rxn.equation

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        if column == self.COL_ID:
            self._reactions.sort(key=lambda r: r.id, reverse=reverse)
        elif column == self.COL_NAME:
            self._reactions.sort(key=lambda r: r.name, reverse=reverse)
        elif column == self.COL_SUBSYSTEM:
            self._reactions.sort(key=lambda r: r.subsystem or "", reverse=reverse)
        elif column == self.COL_GENES:
            self._reactions.sort(key=lambda r: len(r.genes), reverse=reverse)

        self.endResetModel()


class ReactionFilterProxy(QSortFilterProxyModel):
    """Filter proxy for reaction table."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text_filter = ""
        self._subsystem_filter = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_text_filter(self, text: str) -> None:
        self._text_filter = text.lower()
        self.invalidateFilter()

    def set_subsystem_filter(self, subsystem: str) -> None:
        self._subsystem_filter = subsystem
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # type: ignore[override]
        model = self.sourceModel()
        if not isinstance(model, ReactionTableModel):
            return True

        rxn = model.get_reaction(source_row)
        if rxn is None:
            return False

        # Text filter
        if self._text_filter:
            text = self._text_filter
            if (
                text not in rxn.id.lower()
                and text not in rxn.name.lower()
                and text not in rxn.gene_reaction_rule.lower()
            ):
                return False

        # Subsystem filter
        return not (self._subsystem_filter and (rxn.subsystem or "") != self._subsystem_filter)


class ReactionTableWidget(QWidget):
    """Complete reaction table widget with filters."""

    reaction_selected = Signal(str)  # reaction_id
    removal_requested = Signal(str)  # reaction_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = ReactionTableModel()
        self._proxy = ReactionFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Filter bar
        filter_layout = QHBoxLayout()

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search reactions (ID, name, gene)...")
        self._search.textChanged.connect(self._proxy.set_text_filter)
        filter_layout.addWidget(self._search, stretch=2)

        self._subsystem_combo = QComboBox()
        self._subsystem_combo.addItem("All Subsystems", "")
        self._subsystem_combo.currentIndexChanged.connect(self._on_subsystem_changed)
        filter_layout.addWidget(self._subsystem_combo, stretch=1)

        layout.addLayout(filter_layout)

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
        header.setDefaultSectionSize(100)
        # Set sensible initial widths
        header.resizeSection(ReactionTableModel.COL_ID, 100)
        header.resizeSection(ReactionTableModel.COL_NAME, 150)
        header.resizeSection(ReactionTableModel.COL_EQUATION, 200)
        header.resizeSection(ReactionTableModel.COL_SUBSYSTEM, 140)
        header.resizeSection(ReactionTableModel.COL_GENES, 50)
        header.resizeSection(ReactionTableModel.COL_GPR, 120)

        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._table)

    def set_model_data(self, model_data: ModelData) -> None:
        self._model.set_reactions(model_data.reactions)

        # Populate subsystem filter
        self._subsystem_combo.clear()
        self._subsystem_combo.addItem("All Subsystems", "")
        for sub in model_data.get_subsystems():
            self._subsystem_combo.addItem(sub, sub)

    def update_reaction_row(self, reaction_id: str) -> None:
        """Refresh the display for a modified reaction."""
        for row, rxn in enumerate(self._model.reactions):
            if rxn.id == reaction_id:
                left = self._model.index(row, 0)
                right = self._model.index(row, self._model.columnCount() - 1)
                self._model.dataChanged.emit(left, right)
                break

    def _on_subsystem_changed(self, index: int) -> None:
        sub = self._subsystem_combo.currentData() or ""
        self._proxy.set_subsystem_filter(sub)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            source_index = self._proxy.mapToSource(current)
            rxn = self._model.get_reaction(source_index.row())
            if rxn:
                self.reaction_selected.emit(rxn.id)

    def _show_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        source_index = self._proxy.mapToSource(index)
        rxn = self._model.get_reaction(source_index.row())
        if not rxn:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove Reaction...")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == remove_action:
            self.removal_requested.emit(rxn.id)
