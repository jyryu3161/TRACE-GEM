"""Settings dialog for organism and scoring configuration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
)

from src.core.models import EvidenceSource
from src.evidence.evidence_types import SOURCE_REGISTRY, get_ordered_sources
from src.utils.config import Config


class SettingsDialog(QDialog):
    """Settings dialog for configuring organism and evaluation parameters."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        # Dynamic widget storage keyed by EvidenceSource
        self._enable_checks: dict[EvidenceSource, QCheckBox] = {}
        self._weight_spins: dict[EvidenceSource, QDoubleSpinBox] = {}

        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # Organism tab
        org_tab = QGroupBox()
        org_form = QFormLayout(org_tab)

        self._organism_name = QLineEdit()
        self._kegg_code = QLineEdit()

        org_form.addRow("Organism Name:", self._organism_name)
        org_form.addRow("KEGG Organism Code:", self._kegg_code)
        org_form.addRow(
            QLabel("<i>Common codes: eco (E.coli), sce (S.cerevisiae), hsa (H.sapiens)</i>")
        )
        tabs.addTab(org_tab, "Organism")

        # Evidence Sources tab
        source_tab = QGroupBox()
        source_form = QFormLayout(source_tab)

        for source, sc in get_ordered_sources():
            if sc.enable_key:
                check = QCheckBox(f"Enable {sc.display_name}")
                self._enable_checks[source] = check
                source_form.addRow("", check)

            if sc.description:
                source_form.addRow(QLabel(f"<i>{sc.description}</i>"))

        tabs.addTab(source_tab, "Evidence Sources")

        # Scoring Weights tab
        weight_tab = QGroupBox()
        weight_form = QFormLayout(weight_tab)

        for source, sc in get_ordered_sources():
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            self._weight_spins[source] = spin
            weight_form.addRow(f"{sc.display_name}:", spin)

        weight_form.addRow(
            QLabel(
                "<i>Weights are normalized at scoring time. "
                "Inactive sources redistribute weight automatically.</i>"
            )
        )
        tabs.addTab(weight_tab, "Scoring Weights")

        # Evaluation tab
        eval_tab = QGroupBox()
        eval_form = QFormLayout(eval_tab)

        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 50)
        self._max_concurrent = QSpinBox()
        self._max_concurrent.setRange(1, 20)

        eval_form.addRow("Batch Size:", self._batch_size)
        eval_form.addRow("Max Concurrent:", self._max_concurrent)
        tabs.addTab(eval_tab, "Evaluation")

        layout.addWidget(tabs)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_values(self) -> None:
        self._organism_name.setText(self._config.organism_name)
        self._kegg_code.setText(self._config.kegg_organism_code)

        # Load enable flags
        for source, check in self._enable_checks.items():
            sc = SOURCE_REGISTRY[source]
            check.setChecked(getattr(self._config, sc.enable_key, False))

        # Load weights
        for source, spin in self._weight_spins.items():
            sc = SOURCE_REGISTRY[source]
            spin.setValue(getattr(self._config, sc.weight_key, 0.0))

        self._batch_size.setValue(self._config.batch_size)
        self._max_concurrent.setValue(self._config.max_concurrent)

    def _save_and_accept(self) -> None:
        self._config.organism_name = self._organism_name.text()
        self._config.kegg_organism_code = self._kegg_code.text()

        # Save enable flags
        for source, check in self._enable_checks.items():
            sc = SOURCE_REGISTRY[source]
            setattr(self._config, sc.enable_key, check.isChecked())

        # Save weights
        for source, spin in self._weight_spins.items():
            sc = SOURCE_REGISTRY[source]
            setattr(self._config, sc.weight_key, spin.value())

        self._config.batch_size = self._batch_size.value()
        self._config.max_concurrent = self._max_concurrent.value()
        self.accept()
