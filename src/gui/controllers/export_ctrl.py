"""Export controller — manages file export operations."""

from __future__ import annotations

import logging
from pathlib import Path
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

        from src.cli import _save_gapfill_report
        from src.utils.provenance import (
            build_gapfill_manifest,
            write_evidence_snapshot,
            write_manifest,
        )

        tasks = [task_result.task for task_result in result.task_results_before]
        _save_gapfill_report(filepath, result, tasks)
        evidence_path = Path(filepath).with_suffix(".evidence.json.gz")
        write_evidence_snapshot(evidence_path, result)
        manifest = build_gapfill_manifest(
            config=self._w._config,
            result=result,
            model=self._w._model.cobra_model,
            inputs={
                "draft_model": getattr(self._w, "_sbml_filepath", None),
                "universal_model": self._w._loaded_universal_path,
                "task_file": self._w._loaded_tasks_path,
            },
            outputs={"report": filepath, "evidence_snapshot": evidence_path},
            command=["metatask-gapfill", "GUI"],
        )
        write_manifest(Path(filepath).with_suffix(".manifest.json"), manifest)

        self._w._statusbar.showMessage(f"Report exported to {filepath}")
