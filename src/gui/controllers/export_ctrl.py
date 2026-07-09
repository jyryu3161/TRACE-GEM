"""Export controller — manages file export operations."""

from __future__ import annotations

import csv
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.export")


class ExportController:
    """Manages file export operations."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def export_sbml(self) -> None:
        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.warning(self._w, "No Model", "No SBML model loaded.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export SBML",
            f"{self._w._model.id}_modified.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return
        import cobra

        cobra.io.write_sbml_model(self._w._model.cobra_model, filepath)
        self._w._statusbar.showMessage(f"SBML exported to {filepath}")

    def export_improved_sbml(self) -> None:
        """Export the improved model after gap-filling."""
        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.warning(self._w, "No Model", "No model available for export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export Improved SBML",
            f"{self._w._model.id}_improved.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        import cobra

        cobra.io.write_sbml_model(self._w._model.cobra_model, filepath)
        self._w._statusbar.showMessage(f"Improved SBML exported to {filepath}")

    def export_gapfill_report(self) -> None:
        """Export gap-fill added-reactions provenance as CSV."""
        result = self._w._gapfill_panel._result
        if not self._w._model or result is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export Gap-Fill Report",
            f"{self._w._model.id}_gapfill_report.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Reaction ID", "Name", "Evidence Tier", "Weight", "GPR", "Selected"]
            )
            for candidate in result.added_reactions:
                rxn = candidate.reaction
                tier = (
                    candidate.evidence_tier.label if candidate.evidence_tier else "—"
                )
                writer.writerow(
                    [
                        rxn.id,
                        rxn.name,
                        tier,
                        f"{candidate.penalty:.2f}",
                        candidate.assigned_gpr or "",
                        "yes",
                    ]
                )

        self._w._statusbar.showMessage(f"Report exported to {filepath}")
