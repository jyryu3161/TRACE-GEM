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

from src.utils.config import Config


class SettingsDialog(QDialog):
    """Settings dialog for configuring organism, API keys, and evaluation parameters."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
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

        # API Keys tab
        api_tab = QGroupBox()
        api_form = QFormLayout(api_tab)

        self._gemini_key = QLineEdit()
        self._gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_key.setPlaceholderText("Enter Gemini API key")
        self._enable_gemini = QCheckBox("Enable Gemini verification")

        self._perplexity_key = QLineEdit()
        self._perplexity_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._perplexity_key.setPlaceholderText("Enter Perplexity API key")
        self._enable_perplexity = QCheckBox("Enable Perplexity verification")

        api_form.addRow("Gemini API Key:", self._gemini_key)
        api_form.addRow("", self._enable_gemini)
        api_form.addRow(QLabel("<i>Uses Gemini 2.5 Flash to verify KEGG reaction mappings</i>"))
        api_form.addRow("", QLabel(""))  # spacer
        api_form.addRow("Perplexity API Key:", self._perplexity_key)
        api_form.addRow("", self._enable_perplexity)
        api_form.addRow(
            QLabel("<i>Uses Perplexity Sonar for species-specific reaction verification</i>")
        )
        tabs.addTab(api_tab, "API Keys")

        # Scoring Weights tab
        weight_tab = QGroupBox()
        weight_form = QFormLayout(weight_tab)

        self._w_kegg = QDoubleSpinBox()
        self._w_kegg.setRange(0.0, 1.0)
        self._w_kegg.setSingleStep(0.05)
        self._w_kegg.setDecimals(2)

        self._w_gemini = QDoubleSpinBox()
        self._w_gemini.setRange(0.0, 1.0)
        self._w_gemini.setSingleStep(0.05)
        self._w_gemini.setDecimals(2)

        self._w_perplexity = QDoubleSpinBox()
        self._w_perplexity.setRange(0.0, 1.0)
        self._w_perplexity.setSingleStep(0.05)
        self._w_perplexity.setDecimals(2)

        weight_form.addRow("KEGG:", self._w_kegg)
        weight_form.addRow("Gemini:", self._w_gemini)
        weight_form.addRow("Perplexity:", self._w_perplexity)
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

        self._gemini_key.setText(self._config.gemini_api_key or "")
        self._enable_gemini.setChecked(self._config.enable_gemini)
        self._perplexity_key.setText(self._config.perplexity_api_key or "")
        self._enable_perplexity.setChecked(self._config.enable_perplexity)

        self._w_kegg.setValue(self._config.weight_kegg)
        self._w_gemini.setValue(self._config.weight_gemini)
        self._w_perplexity.setValue(self._config.weight_perplexity)

        self._batch_size.setValue(self._config.batch_size)
        self._max_concurrent.setValue(self._config.max_concurrent)

    def _save_and_accept(self) -> None:
        self._config.organism_name = self._organism_name.text()
        self._config.kegg_organism_code = self._kegg_code.text()

        self._config.gemini_api_key = self._gemini_key.text().strip() or None
        self._config.enable_gemini = self._enable_gemini.isChecked()
        self._config.perplexity_api_key = self._perplexity_key.text().strip() or None
        self._config.enable_perplexity = self._enable_perplexity.isChecked()

        self._config.weight_kegg = self._w_kegg.value()
        self._config.weight_gemini = self._w_gemini.value()
        self._config.weight_perplexity = self._w_perplexity.value()

        self._config.batch_size = self._batch_size.value()
        self._config.max_concurrent = self._max_concurrent.value()
        self.accept()
