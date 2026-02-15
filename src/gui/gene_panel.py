"""Gene information panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelData, Reaction


class GenePanelWidget(QWidget):
    """Displays genes associated with a reaction."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model: ModelData | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Associated Genes")
        group_layout = QVBoxLayout(group)

        self._gene_list = QListWidget()
        group_layout.addWidget(self._gene_list)

        layout.addWidget(group)

    def set_model(self, model: ModelData) -> None:
        self._model = model

    def set_reaction(self, reaction: Reaction) -> None:
        self._gene_list.clear()
        for gene_id in reaction.genes:
            gene_obj = None
            if self._model:
                for g in self._model.genes:
                    if g.id == gene_id:
                        gene_obj = g
                        break

            name = gene_obj.name if gene_obj and gene_obj.name else ""
            label = f"{gene_id}" + (f" ({name})" if name else "")
            self._gene_list.addItem(label)

    def clear(self) -> None:
        self._gene_list.clear()
