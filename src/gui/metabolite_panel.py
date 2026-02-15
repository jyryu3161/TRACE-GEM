"""Metabolite information panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.id_mapper import IdentifierMapper
from src.core.models import ModelData, Reaction


class MetabolitePanelWidget(QWidget):
    """Displays metabolites involved in a reaction."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model: ModelData | None = None
        self._mapper: IdentifierMapper | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Reactants
        react_group = QGroupBox("Reactants")
        react_layout = QVBoxLayout(react_group)
        self._reactant_list = QListWidget()
        react_layout.addWidget(self._reactant_list)
        layout.addWidget(react_group)

        # Products
        prod_group = QGroupBox("Products")
        prod_layout = QVBoxLayout(prod_group)
        self._product_list = QListWidget()
        prod_layout.addWidget(self._product_list)
        layout.addWidget(prod_group)

    def set_model(self, model: ModelData) -> None:
        self._model = model

    def set_mapper(self, mapper: IdentifierMapper) -> None:
        """Set the identifier mapper for KEGG compound ID lookup."""
        self._mapper = mapper

    def set_reaction(self, reaction: Reaction) -> None:
        self._reactant_list.clear()
        self._product_list.clear()

        for met_id, coef in reaction.reactants.items():
            name = self._get_met_name(met_id)
            kegg_suffix = self._get_kegg_suffix(met_id)
            self._reactant_list.addItem(f"{coef:.0f} {name} [{met_id}]{kegg_suffix}")

        for met_id, coef in reaction.products.items():
            name = self._get_met_name(met_id)
            kegg_suffix = self._get_kegg_suffix(met_id)
            self._product_list.addItem(f"{coef:.0f} {name} [{met_id}]{kegg_suffix}")

    def clear(self) -> None:
        self._reactant_list.clear()
        self._product_list.clear()

    def _get_met_name(self, met_id: str) -> str:
        if self._model:
            for m in self._model.metabolites:
                if m.id == met_id:
                    return m.name
        return met_id

    def _get_kegg_suffix(self, met_id: str) -> str:
        """Return ' → KEGG: Cxxxxx' if mapper has a KEGG ID for this metabolite."""
        if self._mapper:
            kid = self._mapper.get_metabolite_kegg_id(met_id)
            if kid:
                return f" \u2192 KEGG: {kid}"
        return ""
