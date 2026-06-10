"""Settings dialog for organism and scoring configuration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

        # Model construction (CarveMe) tab
        carveme_tab = QGroupBox()
        carveme_form = QFormLayout(carveme_tab)

        self._carveme_executable = QLineEdit()
        self._carveme_env = QLineEdit()
        self._carveme_env.setPlaceholderText("(optional) conda env containing `carve`")
        self._carveme_diamond = QLineEdit()
        self._carveme_solver = QComboBox()
        # "" = use carve's own default; mirrors the universe combo so an empty
        # config value round-trips instead of being silently rewritten.
        self._carveme_solver.addItems(["", "gurobi", "cplex", "scip"])
        self._carveme_universe = QComboBox()
        self._carveme_universe.addItems(
            ["", "bacteria", "grampos", "gramneg", "archaea", "cyanobacteria"]
        )
        self._carveme_gapfill_media = QLineEdit()
        self._carveme_init_medium = QLineEdit()
        self._carveme_output_dir = QLineEdit()
        self._carveme_timeout = QSpinBox()
        self._carveme_timeout.setRange(60, 36000)
        self._carveme_max_parallel = QSpinBox()
        self._carveme_max_parallel.setRange(1, 16)
        self._carveme_gzip = QCheckBox("Write .xml.gz output")

        carveme_form.addRow("carve executable:", self._carveme_executable)
        carveme_form.addRow("conda env:", self._carveme_env)
        carveme_form.addRow("diamond executable:", self._carveme_diamond)
        carveme_form.addRow("Solver:", self._carveme_solver)
        carveme_form.addRow("Universe:", self._carveme_universe)
        carveme_form.addRow("Gap-fill media (-g):", self._carveme_gapfill_media)
        carveme_form.addRow("Init medium (-i):", self._carveme_init_medium)
        carveme_form.addRow("Output dir:", self._carveme_output_dir)
        carveme_form.addRow("Timeout (s):", self._carveme_timeout)
        carveme_form.addRow("Batch parallelism:", self._carveme_max_parallel)
        carveme_form.addRow("", self._carveme_gzip)
        carveme_form.addRow(
            QLabel("<i>CarveMe runs as an external `carve` subprocess. Default "
                   "solver gurobi; SCIP is the free fallback.</i>")
        )
        tabs.addTab(carveme_tab, "Construction")

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

        # CarveMe construction settings
        self._carveme_executable.setText(self._config.carveme_executable)
        self._carveme_env.setText(self._config.carveme_env)
        self._carveme_diamond.setText(self._config.carveme_diamond_executable)
        self._carveme_solver.setCurrentText(self._config.carveme_solver)
        self._carveme_universe.setCurrentText(self._config.carveme_universe or "")
        self._carveme_gapfill_media.setText(self._config.carveme_gapfill_media)
        self._carveme_init_medium.setText(self._config.carveme_init_medium)
        self._carveme_output_dir.setText(self._config.carveme_output_dir)
        self._carveme_timeout.setValue(self._config.carveme_timeout)
        self._carveme_max_parallel.setValue(self._config.carveme_max_parallel)
        self._carveme_gzip.setChecked(self._config.carveme_gzip_output)

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

        # CarveMe construction settings
        self._config.carveme_executable = self._carveme_executable.text().strip() or "carve"
        self._config.carveme_env = self._carveme_env.text().strip()
        self._config.carveme_diamond_executable = (
            self._carveme_diamond.text().strip() or "diamond"
        )
        self._config.carveme_solver = self._carveme_solver.currentText()
        self._config.carveme_universe = self._carveme_universe.currentText()
        self._config.carveme_gapfill_media = self._carveme_gapfill_media.text().strip()
        self._config.carveme_init_medium = self._carveme_init_medium.text().strip()
        self._config.carveme_output_dir = (
            self._carveme_output_dir.text().strip() or "built_models"
        )
        self._config.carveme_timeout = self._carveme_timeout.value()
        self._config.carveme_max_parallel = self._carveme_max_parallel.value()
        self._config.carveme_gzip_output = self._carveme_gzip.isChecked()
        self.accept()
