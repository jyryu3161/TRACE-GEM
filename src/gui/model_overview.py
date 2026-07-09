"""Model overview panel showing summary information."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelData


class ModelOverviewWidget(QWidget):
    """Displays summary of the loaded metabolic model with tabbed layout."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # --- Model tab ---
        model_page = QWidget()
        form = QFormLayout(model_page)
        form.setContentsMargins(8, 8, 8, 8)

        self._model_id = QLabel("-")
        self._model_name = QLabel("-")
        self._organism = QLabel("-")
        self._kegg_code = QLabel("-")
        self._reactions = QLabel("-")
        self._metabolites = QLabel("-")
        self._genes = QLabel("-")
        self._subsystems = QLabel("-")

        form.addRow("Model ID:", self._model_id)
        form.addRow("Name:", self._model_name)
        form.addRow("Organism:", self._organism)
        form.addRow("KEGG Code:", self._kegg_code)
        form.addRow("Reactions:", self._reactions)
        form.addRow("Metabolites:", self._metabolites)
        form.addRow("Genes:", self._genes)
        form.addRow("Subsystems:", self._subsystems)

        self._tabs.addTab(model_page, "Model")

        # --- Universal tab (added dynamically when loaded) ---
        self._universal_page = QWidget()
        uform = QFormLayout(self._universal_page)
        uform.setContentsMargins(8, 8, 8, 8)

        self._uni_model_id = QLabel("-")
        self._uni_total = QLabel("-")
        self._uni_excluded = QLabel("-")
        self._uni_candidates = QLabel("-")
        self._uni_evaluated = QLabel("0 / 0")

        uform.addRow("Model ID:", self._uni_model_id)
        uform.addRow("Total Reactions:", self._uni_total)
        uform.addRow("Excluded:", self._uni_excluded)
        uform.addRow("Candidates:", self._uni_candidates)
        uform.addRow("Evaluated:", self._uni_evaluated)

        self._universal_tab_index: int | None = None

        layout.addWidget(self._tabs)

    def set_model(self, model: ModelData) -> None:
        self._model_id.setText(model.id)
        self._model_name.setText(model.name)
        self._organism.setText(model.organism or "Unknown")
        self._kegg_code.setText(model.kegg_organism_code or "Not set")
        self._reactions.setText(str(model.reaction_count))
        self._metabolites.setText(str(model.metabolite_count))
        self._genes.setText(str(model.gene_count))
        self._subsystems.setText(str(len(model.get_subsystems())))

    def set_universal_info(
        self,
        model_id: str,
        total_reactions: int,
        excluded: int,
        candidates: int,
    ) -> None:
        """Show universal model summary as a tab."""
        self._uni_model_id.setText(model_id)
        self._uni_total.setText(str(total_reactions))
        self._uni_excluded.setText(f"{excluded} (model + exchange)")
        self._uni_candidates.setText(str(candidates))
        self._uni_evaluated.setText(f"0 / {candidates}")

        if self._universal_tab_index is None:
            self._universal_tab_index = self._tabs.addTab(
                self._universal_page, "Universal"
            )
        self._tabs.setCurrentIndex(self._universal_tab_index)

    def update_universal_evaluation_count(self, evaluated: int, total: int) -> None:
        self._uni_evaluated.setText(f"{evaluated} / {total}")

    def clear_universal(self) -> None:
        if self._universal_tab_index is not None:
            self._tabs.removeTab(self._universal_tab_index)
            self._universal_tab_index = None
