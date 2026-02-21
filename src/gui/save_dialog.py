"""Save dialog with version control and QC options."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from src.core.models import ModelVersion
from src.utils.config import Config


class SaveDialog(QDialog):
    """Dialog for saving a model version with optional QC."""

    def __init__(
        self,
        config: Config,
        current_version: ModelVersion | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._current_version = current_version
        self.setWindowTitle("Save Model Version")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Change type dropdown
        self._change_type = QComboBox()
        self._change_type.addItems([
            "manual_edit",
            "gap_fill",
            "initial_load",
            "restore",
        ])
        form.addRow("Change Type:", self._change_type)

        # Description text
        self._description = QTextEdit()
        self._description.setPlaceholderText(
            "Describe the changes (auto-generated if left empty)"
        )
        self._description.setMaximumHeight(80)
        form.addRow("Description:", self._description)

        layout.addLayout(form)

        # Checkboxes
        self._run_qc = QCheckBox("Run Metabolic Task QC before saving")
        self._run_qc.setChecked(True)
        layout.addWidget(self._run_qc)

        self._export_sbml = QCheckBox("Also export SBML file copy")
        layout.addWidget(self._export_sbml)

        # Previous version info
        if self._current_version:
            vid = self._current_version.version_id
            rate = self._current_version.task_pass_rate or "N/A"
            info = QLabel(f"Previous: {vid} ({rate} tasks passed)")
            info.setStyleSheet("color: #7f8c8d; margin-top: 8px;")
            layout.addWidget(info)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_options(self) -> dict:
        """Return dialog selections.

        Returns:
            Dict with keys: change_type, description, run_qc, export_sbml.
        """
        desc = self._description.toPlainText().strip()
        return {
            "change_type": self._change_type.currentText(),
            "description": desc if desc else None,
            "run_qc": self._run_qc.isChecked(),
            "export_sbml": self._export_sbml.isChecked(),
        }
