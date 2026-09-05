"""Version controller — manages model version control."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from src.core.cobra_utils import sync_model_data_from_cobra
from src.gui.diff_dialog import DiffDialog
from src.gui.save_dialog import SaveDialog

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.version")


class VersionController:
    """Manages model version control."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def on_reaction_modified(self, reaction_id: str) -> None:
        """Handle reaction edits from the detail panel."""
        if self._w._model:
            rxn = self._w._model.get_reaction(reaction_id)
            if rxn:
                self._w._reaction_table.update_reaction_row(reaction_id)
        self._w._statusbar.showMessage(f"Reaction {reaction_id} modified")

        # Auto-save version on edit if enabled
        if (
            self._w._config.auto_save_on_edit
            and self._w._version_manager
            and self._w._model
            and self._w._model.cobra_model
        ):
            self.auto_save_version("manual_edit")

    def save_version(self) -> None:
        """Show the save dialog and save a new version."""
        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.warning(self._w, "No Model", "Load an SBML model first.")
            return
        if not self._w._version_manager:
            QMessageBox.warning(self._w, "Versioning Disabled", "Version control is not active.")
            return

        current = self._w._version_manager.current_version
        dialog = SaveDialog(self._w._config, current, self._w)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.get_options()

        # Run QC if requested
        task_results = None
        if options["run_qc"]:
            task_results = self.run_qc_for_version()

        # Save version
        self.do_save_version(
            change_type=options["change_type"],
            custom_description=options["description"],
            task_results=task_results,
        )

        # Export SBML copy if requested
        if options["export_sbml"]:
            self._w._export_ctrl.export_sbml()

    def do_save_version(
        self,
        change_type: str,
        custom_description: str | None = None,
        task_results=None,
    ) -> None:
        """Save a version synchronously by running async in a new event loop."""
        if not self._w._version_manager or not self._w._model or not self._w._model.cobra_model:
            return

        try:
            loop = asyncio.new_event_loop()
            try:
                version = loop.run_until_complete(
                    self._w._version_manager.save_version(
                        self._w._model.cobra_model,
                        change_type,
                        task_results=task_results,
                        custom_description=custom_description,
                    )
                )
            finally:
                loop.close()

            self._w._version_panel.set_history(
                self._w._version_manager.get_history(),
                self._w._version_manager.current_version.version_id
                if self._w._version_manager.current_version
                else None,
            )
            self._w._mark_dirty()
            self._w._statusbar.showMessage(
                f"Saved version {version.version_id}: {version.description}"
            )
        except Exception as e:
            logger.warning("Failed to save version: %s", e)
            QMessageBox.warning(self._w, "Version Save Error", str(e))

    def auto_save_version(self, change_type: str) -> None:
        """Auto-save a version without showing dialog."""
        if not self._w._version_manager or not self._w._model or not self._w._model.cobra_model:
            return
        self.do_save_version(change_type=change_type)

    def restore_version(self, version_id: str) -> None:
        """Restore a specific version."""
        if not self._w._version_manager or not self._w._model:
            return

        try:
            restored_model = self._w._version_manager.restore_version(version_id)

            # Refresh both the COBRA model and the GUI-facing ModelData lists.
            sync_model_data_from_cobra(self._w._model, restored_model)
            self._w._mark_dirty()

            # Refresh all panels
            self._w._reaction_table.set_model_data(self._w._model)
            self._w._overview.set_model(self._w._model)
            self._w._gene_panel.set_model(self._w._model)
            self._w._metabolite_panel.set_model(self._w._model)
            self._w._reaction_detail.clear()
            self._w._evidence_panel.clear()
            self._w._version_panel.set_history(
                self._w._version_manager.get_history(),
                self._w._version_manager.current_version.version_id
                if self._w._version_manager.current_version
                else None,
            )

            self._w._statusbar.showMessage(f"Restored to version {version_id}")
        except Exception as e:
            logger.warning("Failed to restore version: %s", e)
            QMessageBox.critical(self._w, "Restore Error", str(e))

    def show_version_detail(self, version_id: str) -> None:
        """Show diff details for a single version (double-click)."""
        if not self._w._version_manager:
            return

        history = self._w._version_manager.get_history()
        version = next((v for v in history if v.version_id == version_id), None)
        if not version:
            return

        diff = version.diff
        if diff is None or diff.is_empty:
            QMessageBox.information(
                self._w,
                "Version Detail",
                f"No recorded changes for {version_id}.",
            )
            return

        dialog = DiffDialog.from_single_version(version, self._w)
        dialog.exec()

    def compare_versions(self, version_a: str, version_b: str) -> None:
        """Show a diff dialog comparing two versions."""
        if not self._w._version_manager:
            return

        try:
            diff = self._w._version_manager.compare_versions(version_a, version_b)
            history = self._w._version_manager.get_history()

            meta_a = next((v for v in history if v.version_id == version_a), None)
            meta_b = next((v for v in history if v.version_id == version_b), None)

            if not meta_a or not meta_b:
                QMessageBox.warning(self._w, "Compare Error", "Could not find version metadata.")
                return

            dialog = DiffDialog(diff, meta_a, meta_b, self._w)
            dialog.exec()
        except Exception as e:
            logger.warning("Failed to compare versions: %s", e)
            QMessageBox.critical(self._w, "Compare Error", str(e))

    def rename_version(self, version_id: str, new_id: str) -> None:
        """Rename a version ID."""
        if not self._w._version_manager:
            return
        try:
            self._w._version_manager.rename_version(version_id, new_id)
            self._w._version_panel.set_history(
                self._w._version_manager.get_history(),
                self._w._version_manager.current_version.version_id
                if self._w._version_manager.current_version
                else None,
            )
            self._w._statusbar.showMessage(f"Renamed version {version_id} → {new_id}")
        except Exception as e:
            QMessageBox.critical(self._w, "Rename Error", str(e))

    def update_description(self, version_id: str, new_description: str) -> None:
        """Update description of a version."""
        if not self._w._version_manager:
            return
        try:
            self._w._version_manager.update_description(version_id, new_description)
            self._w._version_panel.set_history(
                self._w._version_manager.get_history(),
                self._w._version_manager.current_version.version_id
                if self._w._version_manager.current_version
                else None,
            )
            self._w._statusbar.showMessage(f"Updated description for {version_id}")
        except Exception as e:
            QMessageBox.critical(self._w, "Description Error", str(e))

    def delete_version(self, version_id: str) -> None:
        """Delete a version."""
        if not self._w._version_manager:
            return
        try:
            self._w._version_manager.delete_version(version_id)
            self._w._version_panel.set_history(
                self._w._version_manager.get_history(),
                self._w._version_manager.current_version.version_id
                if self._w._version_manager.current_version
                else None,
            )
            self._w._statusbar.showMessage(f"Deleted version {version_id}")
        except Exception as e:
            QMessageBox.critical(self._w, "Delete Error", str(e))

    def export_version_sbml(self, version_id: str) -> None:
        """Export a specific version as SBML."""
        if not self._w._version_manager:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export Version SBML",
            f"{version_id}_model.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        try:
            import cobra

            model, _ = self._w._version_manager._storage.load_version(
                self._w._version_manager._model_id, version_id
            )
            cobra.io.write_sbml_model(model, filepath)
            self._w._statusbar.showMessage(f"Exported {version_id} to {filepath}")
        except Exception as e:
            QMessageBox.critical(self._w, "Export Error", str(e))

    def run_qc_for_version(self):
        """Run metabolic task QC and return results."""
        if not self._w._model or not self._w._model.cobra_model:
            return None

        try:
            from src.core.task_parser import TaskParser, TaskRunner

            task_file = self._w._config.default_task_file
            parser = TaskParser()
            tasks = parser.parse(task_file)
            runner = TaskRunner()
            return runner.run_all(self._w._model.cobra_model, tasks)
        except Exception as e:
            logger.warning("QC run failed: %s", e)
            return None
