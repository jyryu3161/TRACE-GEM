"""Model overview panel showing summary information."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelData


class ModelOverviewWidget(QWidget):
    """Displays summary of the loaded metabolic model."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Model Overview")
        form = QFormLayout(group)

        self._model_id = QLabel("-")
        self._model_name = QLabel("-")
        self._organism = QLabel("-")
        self._reactions = QLabel("-")
        self._metabolites = QLabel("-")
        self._genes = QLabel("-")
        self._subsystems = QLabel("-")
        self._kegg_code = QLabel("-")
        self._evaluated = QLabel("0 / 0")

        form.addRow("Model ID:", self._model_id)
        form.addRow("Name:", self._model_name)
        form.addRow("Organism:", self._organism)
        form.addRow("KEGG Code:", self._kegg_code)
        form.addRow("Reactions:", self._reactions)
        form.addRow("Metabolites:", self._metabolites)
        form.addRow("Genes:", self._genes)
        form.addRow("Subsystems:", self._subsystems)
        form.addRow("Evaluated:", self._evaluated)

        layout.addWidget(group)
        layout.addStretch()

    def set_model(self, model: ModelData) -> None:
        self._model_id.setText(model.id)
        self._model_name.setText(model.name)
        self._organism.setText(model.organism or "Unknown")
        self._kegg_code.setText(model.kegg_organism_code or "Not set")
        self._reactions.setText(str(model.reaction_count))
        self._metabolites.setText(str(model.metabolite_count))
        self._genes.setText(str(model.gene_count))
        self._subsystems.setText(str(len(model.get_subsystems())))

    def update_evaluation_count(self, evaluated: int, total: int) -> None:
        self._evaluated.setText(f"{evaluated} / {total}")
