"""Workflow wizard dialog for gap-filling setup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from src.core.models import ModelData
from src.utils.config import Config
from src.utils.constants import DEFAULT_TASK_FILE, DEFAULT_UNIVERSAL_MODEL


class WorkflowWizard(QDialog):
    """Dialog for configuring gap-filling workflow parameters.

    Collects:
    - Step 1: Model info (read-only) + organism
    - Step 2: Universal model selection (default / custom)
    - Step 3: Metabolic tasks selection (default / custom / skip)
    - Step 4: Workflow options (evaluate, filter, gap-fill, assign GPR)

    Returns a dict with all selections via get_selections() after accept().
    """

    def __init__(
        self,
        config: Config,
        model: ModelData | None = None,
        parent=None,
        universal_path: str | None = None,
        loaded_tasks: list | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._model = model
        self._preloaded_universal_path = universal_path
        self._preloaded_tasks = loaded_tasks

        self.setWindowTitle("Task-Based Gap-Filling Setup")
        self.setMinimumWidth(520)

        self._setup_ui()

        # Pre-populate with already-loaded universal model path
        if self._preloaded_universal_path:
            self._universal_custom.setChecked(True)
            self._universal_path.setText(self._preloaded_universal_path)

        # Pre-select loaded tasks if available
        if self._preloaded_tasks:
            self._task_preloaded.setChecked(True)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Step 1: Model & Organism
        layout.addWidget(self._build_step1())

        # Step 2: Universal Model
        layout.addWidget(self._build_step2())

        # Step 3: Metabolic Tasks
        layout.addWidget(self._build_step3())

        # Step 4: Options
        layout.addWidget(self._build_step4())

        # Buttons
        buttons = QDialogButtonBox()
        self._start_btn = buttons.addButton("Start Gap-Filling", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_step1(self) -> QGroupBox:
        """Step 1: Model & Organism info (read-only)."""
        group = QGroupBox("Step 1: Model && Organism")
        form = QFormLayout(group)

        model_name = self._model.name if self._model else "(no model loaded)"
        model_id = self._model.id if self._model else ""
        rxn_count = str(self._model.reaction_count) if self._model else "0"

        form.addRow("Model:", QLabel(f"<b>{model_name}</b> ({model_id})"))
        form.addRow("Reactions:", QLabel(rxn_count))

        self._organism_code = QLineEdit(self._config.kegg_organism_code)
        self._organism_code.setPlaceholderText("e.g. eco")
        form.addRow("KEGG Organism Code:", self._organism_code)

        self._organism_name = QLineEdit(self._config.organism_name)
        self._organism_name.setPlaceholderText("e.g. Escherichia coli")
        form.addRow("Organism Name:", self._organism_name)

        return group

    def _build_step2(self) -> QGroupBox:
        """Step 2: Universal model selection."""
        group = QGroupBox("Step 2: Universal Model")
        vlayout = QVBoxLayout(group)

        self._universal_group = QButtonGroup(self)

        self._universal_default = QRadioButton("Default (BiGG Universal)")
        self._universal_default.setChecked(True)
        self._universal_group.addButton(self._universal_default, 0)
        vlayout.addWidget(self._universal_default)

        custom_row = QHBoxLayout()
        self._universal_custom = QRadioButton("Custom:")
        self._universal_group.addButton(self._universal_custom, 1)
        custom_row.addWidget(self._universal_custom)

        self._universal_path = QLineEdit()
        self._universal_path.setPlaceholderText("Select universal model file...")
        self._universal_path.setEnabled(False)
        custom_row.addWidget(self._universal_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_universal)
        custom_row.addWidget(browse_btn)

        vlayout.addLayout(custom_row)

        # Enable/disable path field based on radio selection
        self._universal_group.buttonToggled.connect(self._on_universal_toggled)

        return group

    def _build_step3(self) -> QGroupBox:
        """Step 3: Metabolic tasks selection."""
        group = QGroupBox("Step 3: Metabolic Tasks")
        vlayout = QVBoxLayout(group)

        self._task_group = QButtonGroup(self)

        # Pre-loaded option (only visible when tasks were loaded via File menu)
        task_count = len(self._preloaded_tasks) if self._preloaded_tasks else 0
        self._task_preloaded = QRadioButton(f"Pre-loaded ({task_count} tasks)")
        self._task_preloaded.setEnabled(bool(self._preloaded_tasks))
        self._task_group.addButton(self._task_preloaded, 3)
        if self._preloaded_tasks:
            vlayout.addWidget(self._task_preloaded)

        self._task_default = QRadioButton("Default (Universal Essential Tasks)")
        self._task_default.setChecked(not self._preloaded_tasks)
        self._task_group.addButton(self._task_default, 0)
        vlayout.addWidget(self._task_default)

        custom_row = QHBoxLayout()
        self._task_custom = QRadioButton("Custom:")
        self._task_group.addButton(self._task_custom, 1)
        custom_row.addWidget(self._task_custom)

        self._task_path = QLineEdit()
        self._task_path.setPlaceholderText("Select task CSV file...")
        self._task_path.setEnabled(False)
        custom_row.addWidget(self._task_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_tasks)
        custom_row.addWidget(browse_btn)

        vlayout.addLayout(custom_row)

        self._task_skip = QRadioButton("Skip tasks (gap-fill only)")
        self._task_group.addButton(self._task_skip, 2)
        vlayout.addWidget(self._task_skip)

        self._task_group.buttonToggled.connect(self._on_task_toggled)

        return group

    def _build_step4(self) -> QGroupBox:
        """Step 4: Workflow options."""
        group = QGroupBox("Step 4: Options")
        vlayout = QVBoxLayout(group)

        self._opt_evaluate_candidates = QCheckBox("Evaluate candidate reactions")
        self._opt_evaluate_candidates.setChecked(True)
        vlayout.addWidget(self._opt_evaluate_candidates)

        self._opt_filter_organism = QCheckBox("Filter by organism (KEGG)")
        self._opt_filter_organism.setChecked(True)
        vlayout.addWidget(self._opt_filter_organism)

        self._opt_gap_fill = QCheckBox("Run gap-filling")
        self._opt_gap_fill.setChecked(True)
        vlayout.addWidget(self._opt_gap_fill)

        self._opt_exclude_exchange_gapfill = QCheckBox(
            "Exclude exchange reactions from gap-filling"
        )
        self._opt_exclude_exchange_gapfill.setChecked(True)
        vlayout.addWidget(self._opt_exclude_exchange_gapfill)

        self._opt_assign_gpr = QCheckBox("Assign GPR from KEGG")
        self._opt_assign_gpr.setChecked(True)
        vlayout.addWidget(self._opt_assign_gpr)

        return group

    # --- Slot handlers ---

    def _on_universal_toggled(self) -> None:
        is_custom = self._universal_custom.isChecked()
        self._universal_path.setEnabled(is_custom)

    def _on_task_toggled(self) -> None:
        is_custom = self._task_custom.isChecked()
        self._task_path.setEnabled(is_custom)

    def _browse_universal(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Universal Model",
            "",
            "Model Files (*.json *.xml *.sbml);;All Files (*)",
        )
        if filepath:
            self._universal_path.setText(filepath)
            self._universal_custom.setChecked(True)

    def _browse_tasks(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Task File",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if filepath:
            self._task_path.setText(filepath)
            self._task_custom.setChecked(True)

    # --- Public API ---

    def get_selections(self) -> dict:
        """Return all wizard selections as a dictionary.

        Keys:
            organism_code: str
            organism_name: str
            universal_model_path: str  (resolved to default or custom path)
            task_file_path: str | None  (None if skipped)
            evaluate_candidates: bool
            filter_organism: bool
            gap_fill: bool
            assign_gpr: bool
        """
        # Universal model path
        if self._universal_custom.isChecked() and self._universal_path.text().strip():
            universal_path = self._universal_path.text().strip()
        else:
            universal_path = str(
                Path(self._config.default_universal_model)
                if self._config.default_universal_model
                else DEFAULT_UNIVERSAL_MODEL
            )

        # Task file path
        use_preloaded = self._task_preloaded.isChecked() and self._preloaded_tasks
        if self._task_skip.isChecked():
            task_path = None
        elif use_preloaded:
            task_path = "__preloaded__"
        elif self._task_custom.isChecked() and self._task_path.text().strip():
            task_path = self._task_path.text().strip()
        else:
            task_path = str(
                Path(self._config.default_task_file)
                if self._config.default_task_file
                else DEFAULT_TASK_FILE
            )

        result = {
            "organism_code": self._organism_code.text().strip().lower(),
            "organism_name": self._organism_name.text().strip(),
            "universal_model_path": universal_path,
            "task_file_path": task_path,
            "evaluate_candidates": self._opt_evaluate_candidates.isChecked(),
            "filter_organism": self._opt_filter_organism.isChecked(),
            "gap_fill": self._opt_gap_fill.isChecked(),
            "exclude_exchange_gapfill": self._opt_exclude_exchange_gapfill.isChecked(),
            "assign_gpr": self._opt_assign_gpr.isChecked(),
        }

        if use_preloaded:
            result["preloaded_tasks"] = self._preloaded_tasks

        return result
