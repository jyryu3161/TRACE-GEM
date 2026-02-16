"""Settings dialog for organism, API keys, and scoring configuration."""

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
    """Settings dialog for configuring organism, API keys, and evaluation parameters."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        # Dynamic widget storage keyed by EvidenceSource
        self._enable_checks: dict[EvidenceSource, QCheckBox] = {}
        self._api_key_edits: dict[EvidenceSource, QLineEdit] = {}
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
        self._uniprot_taxonomy = QLineEdit()

        org_form.addRow("Organism Name:", self._organism_name)
        org_form.addRow("KEGG Organism Code:", self._kegg_code)
        org_form.addRow("UniProt Taxonomy ID:", self._uniprot_taxonomy)
        org_form.addRow(
            QLabel("<i>Common codes: eco (E.coli), sce (S.cerevisiae), hsa (H.sapiens)</i>")
        )
        tabs.addTab(org_tab, "Organism")

        # API Keys tab — dynamic from SOURCE_REGISTRY
        api_tab = QGroupBox()
        api_form = QFormLayout(api_tab)

        for source, sc in get_ordered_sources():
            if sc.requires_api_key or sc.config_key:
                key_edit = QLineEdit()
                key_edit.setEchoMode(QLineEdit.EchoMode.Password)
                key_edit.setPlaceholderText(f"Enter {sc.display_name} API key")
                self._api_key_edits[source] = key_edit
                api_form.addRow(f"{sc.display_name} API Key:", key_edit)

            if sc.enable_key:
                check = QCheckBox(f"Enable {sc.display_name}")
                self._enable_checks[source] = check
                api_form.addRow("", check)

            if sc.description and (sc.requires_api_key or sc.config_key):
                api_form.addRow(QLabel(f"<i>{sc.description}</i>"))
                api_form.addRow("", QLabel(""))  # spacer

        # PubMed email (special field)
        self._pubmed_email = QLineEdit()
        self._pubmed_email.setPlaceholderText("Email for NCBI E-utilities")
        api_form.addRow("PubMed Email:", self._pubmed_email)

        tabs.addTab(api_tab, "API Keys")

        # Scoring Weights tab — dynamic 7 sources
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
        self._uniprot_taxonomy.setText(self._config.uniprot_taxonomy_id)
        self._pubmed_email.setText(self._config.pubmed_email or "")

        # Load enable flags
        for source, check in self._enable_checks.items():
            sc = SOURCE_REGISTRY[source]
            check.setChecked(getattr(self._config, sc.enable_key, False))

        # Load API keys
        for source, edit in self._api_key_edits.items():
            sc = SOURCE_REGISTRY[source]
            if sc.config_key:
                edit.setText(getattr(self._config, sc.config_key, "") or "")

        # Load weights
        for source, spin in self._weight_spins.items():
            sc = SOURCE_REGISTRY[source]
            spin.setValue(getattr(self._config, sc.weight_key, 0.0))

        self._batch_size.setValue(self._config.batch_size)
        self._max_concurrent.setValue(self._config.max_concurrent)

    def _save_and_accept(self) -> None:
        self._config.organism_name = self._organism_name.text()
        self._config.kegg_organism_code = self._kegg_code.text()
        self._config.uniprot_taxonomy_id = self._uniprot_taxonomy.text().strip() or "83333"
        self._config.pubmed_email = self._pubmed_email.text().strip() or None

        # Save enable flags
        for source, check in self._enable_checks.items():
            sc = SOURCE_REGISTRY[source]
            setattr(self._config, sc.enable_key, check.isChecked())

        # Save API keys
        for source, edit in self._api_key_edits.items():
            sc = SOURCE_REGISTRY[source]
            if sc.config_key:
                val = edit.text().strip() or None
                setattr(self._config, sc.config_key, val)

        # Save weights
        for source, spin in self._weight_spins.items():
            sc = SOURCE_REGISTRY[source]
            setattr(self._config, sc.weight_key, spin.value())

        self._config.batch_size = self._batch_size.value()
        self._config.max_concurrent = self._max_concurrent.value()
        self.accept()
