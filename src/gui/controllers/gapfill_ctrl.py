"""Gap-fill controller — manages gap-filling workflow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from src.core.models import GapFillResult, WorkflowCheckpoint
from src.gui.progress_dialog import ProgressDialog
from src.gui.workers import EvaluateBatchWorker, GapFillWorkflowWorker, TaskRunWorker

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("gem_evaluator.gui.gapfill")


class GapFillController:
    """Manages gap-filling workflow."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def start_workflow(self) -> None:
        """Open the workflow wizard and start gap-filling."""
        if not self._w._model:
            QMessageBox.warning(self._w, "No Model", "Load an SBML model first.")
            return

        if self._w._workflow_checkpoint:
            cp = self._w._workflow_checkpoint
            reply = QMessageBox.question(
                self._w,
                "Resume Workflow",
                f"Previous analysis completed up to Phase {cp.completed_phase}/5.\n"
                f"Resume from where it left off?\n\n"
                f"Timestamp: {cp.timestamp}",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                self.resume_workflow()
                return
            self._w._workflow_checkpoint = None

        from src.gui.workflow_wizard import WorkflowWizard

        wizard = WorkflowWizard(
            self._w._config, self._w._model, self._w,
            universal_path=self._w._loaded_universal_path,
            loaded_tasks=self._w._loaded_tasks,
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return

        selections = wizard.get_selections()
        self.run_gapfill_workflow(selections)

    def resume_workflow(self) -> None:
        """Resume a cancelled workflow from checkpoint."""
        cp = self._w._workflow_checkpoint
        if not cp or not self._w._model:
            return

        dialog = ProgressDialog("Gap-Fill Workflow (Resume)", self._w)

        worker = GapFillWorkflowWorker(
            config=self._w._config,
            model_data=self._w._model,
            universal_path=cp.universal_path,
            task_path=cp.task_path,
            evidence_engine=self._w._engine,
            options=cp.options,
            start_phase=cp.completed_phase + 1,
            preloaded_before=cp.result.task_results_before if cp.result else None,
            preloaded_candidates=cp.result.all_candidates if cp.result else None,
        )
        self._w._gapfill_worker = worker
        self._w._active_workers.append(worker)

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            display = f"[Resume Phase {cp.completed_phase + 1}+] [{phase}] {detail}"
            dialog.update_progress(current, total, display)

        worker.signals.progress.connect(on_progress)
        worker.signals.result.connect(lambda r: self.on_gapfill_complete(r, dialog))
        worker.signals.cancelled.connect(
            lambda r, p: self.on_gapfill_cancelled(r, p, dialog, cp.options)
        )
        worker.signals.error.connect(lambda e: self.on_gapfill_error(e, dialog))
        worker.signals.finished.connect(
            lambda: self._w._active_workers.remove(worker) if worker in self._w._active_workers else None
        )
        dialog.cancelled.connect(worker.cancel)

        self._w._workflow_checkpoint = None
        self._w._thread_pool.start(worker)
        dialog.exec()

    def load_task_file(self) -> None:
        """Load a metabolic task CSV file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self._w,
            "Load Metabolic Task File",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        try:
            from src.core.task_parser import TaskParser

            parser = TaskParser()
            tasks = parser.parse(filepath)
        except Exception as e:
            QMessageBox.critical(self._w, "Error Loading Tasks", str(e))
            return

        self._w._loaded_tasks = tasks
        self._w._statusbar.showMessage(
            f"Loaded {len(tasks)} metabolic tasks from {Path(filepath).name}"
        )

        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.information(
                self._w,
                "Tasks Loaded",
                f"Loaded {len(tasks)} tasks.\n"
                "Load an SBML model to run analysis.",
            )
            return

        reply = QMessageBox.question(
            self._w,
            "Run Metabolic Task Analysis",
            f"Loaded {len(tasks)} tasks from:\n{Path(filepath).name}\n\n"
            "Run FBA analysis on all tasks now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.run_task_analysis(tasks)

    def run_task_analysis(self, tasks: list) -> None:
        """Run metabolic task analysis in a background thread."""
        dialog = ProgressDialog("Metabolic Task Analysis", self._w)

        worker = TaskRunWorker(self._w._model.cobra_model, tasks)

        def on_progress(current: int, total: int, detail: str) -> None:
            percent = int(current / total * 100) if total > 0 else 0
            dialog._progress_bar.setValue(percent)
            dialog._status_label.setText(f"Running task {current} / {total}...")
            dialog._detail_label.setText(detail)

        def on_result(results: object) -> None:
            self._w._task_panel.set_results(results)
            self._w._right_tabs.setCurrentWidget(self._w._task_panel)
            passed = sum(1 for r in results if r.passed)
            self._w._statusbar.showMessage(f"{passed}/{len(results)} tasks passed")
            dialog.set_complete()

        def on_error(msg: str) -> None:
            dialog.accept()
            QMessageBox.critical(self._w, "Task Analysis Error", msg)

        worker.signals.progress.connect(on_progress)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: None)

        self._w._thread_pool.start(worker)
        dialog.exec()

    def run_gapfill_workflow(self, selections: dict) -> None:
        """Start the gap-filling workflow, with optional pre-evaluation."""
        if not self._w._model:
            return

        if selections.get("evaluate_model") and self._w._engine:
            results = self._w._engine.get_all_results()
            unevaluated = [r for r in self._w._model.reactions if r.id not in results]
            if unevaluated:
                reply = QMessageBox.information(
                    self._w,
                    "Pre-evaluation Required",
                    f"{len(unevaluated)} model reactions have not been evaluated yet.\n"
                    "They will be evaluated before gap-filling begins.",
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return

                pre_dialog = ProgressDialog("Evaluating Unevaluated Reactions", self._w)
                pre_worker = EvaluateBatchWorker(self._w._engine, unevaluated)
                self._w._batch_worker = pre_worker

                pre_done = {"finished": False}

                def on_pre_complete(r: object) -> None:
                    self._w._eval_ctrl.on_batch_complete(r, pre_dialog)
                    pre_done["finished"] = True

                def on_pre_error(e: str) -> None:
                    self._w._eval_ctrl.on_batch_error(e, pre_dialog)

                pre_worker.signals.progress.connect(pre_dialog.update_progress)
                pre_worker.signals.result.connect(on_pre_complete)
                pre_worker.signals.error.connect(on_pre_error)
                pre_dialog.cancelled.connect(pre_worker.cancel)

                self._w._thread_pool.start(pre_worker)
                pre_dialog.exec()

                if not pre_done["finished"]:
                    return

        self.start_gapfill_worker(selections)

    def start_gapfill_worker(self, selections: dict) -> None:
        """Spawn the GapFillWorkflowWorker."""
        dialog = ProgressDialog("Gap-Fill Workflow", self._w)

        worker = GapFillWorkflowWorker(
            config=self._w._config,
            model_data=self._w._model,
            universal_path=selections.get("universal_model_path", ""),
            task_path=selections.get("task_file_path"),
            evidence_engine=self._w._engine,
            options=selections,
        )
        self._w._gapfill_worker = worker
        self._w._active_workers.append(worker)

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            display = f"[{phase}] {detail}"
            dialog.update_progress(current, total, display)

        worker.signals.progress.connect(on_progress)
        worker.signals.result.connect(lambda r: self.on_gapfill_complete(r, dialog))
        worker.signals.cancelled.connect(
            lambda r, p: self.on_gapfill_cancelled(r, p, dialog, selections)
        )
        worker.signals.error.connect(lambda e: self.on_gapfill_error(e, dialog))
        worker.signals.finished.connect(
            lambda: self._w._active_workers.remove(worker) if worker in self._w._active_workers else None
        )
        dialog.cancelled.connect(worker.cancel)

        self._w._thread_pool.start(worker)
        dialog.exec()

    def on_gapfill_complete(self, result: object, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        self._w._gapfill_worker = None

        if not isinstance(result, GapFillResult):
            return

        if result.task_results_before:
            after = result.task_results_after if result.task_results_after else None
            self._w._task_panel.set_results(result.task_results_before, after)

        self._w._gapfill_panel.set_result(result)

        if result.added_reactions:
            self._w._universal_table.set_candidates(result.added_reactions)
            self._w._left_tabs.setCurrentWidget(self._w._universal_table)

        self._w._right_tabs.setCurrentWidget(self._w._gapfill_panel)

        self._w._statusbar.showMessage(
            f"Gap-fill complete: {len(result.added_reactions)} reactions added, "
            f"{result.tasks_fixed}/{result.total_tasks} tasks fixed"
        )
        logger.info(
            "Gap-fill complete: %d added, %d/%d fixed",
            len(result.added_reactions),
            result.tasks_fixed,
            result.total_tasks,
        )

        if self._w._version_manager and self._w._model and self._w._model.cobra_model:
            task_results = result.task_results_after or result.task_results_before or None
            self._w._version_ctrl.do_save_version(
                change_type="gap_fill",
                task_results=task_results,
            )

    def on_gapfill_cancelled(
        self,
        result: GapFillResult,
        completed_phase: int,
        dialog: ProgressDialog,
        selections: dict,
    ) -> None:
        """Handle workflow cancellation with partial results."""
        from datetime import datetime

        dialog.set_complete()
        self._w._gapfill_worker = None

        self._w._workflow_checkpoint = WorkflowCheckpoint(
            completed_phase=completed_phase,
            result=result,
            universal_path=selections.get("universal_model_path", ""),
            task_path=selections.get("task_file_path"),
            options=selections,
            timestamp=datetime.now().isoformat(),
        )

        if completed_phase >= 1 and result.task_results_before:
            self._w._task_panel.set_results(result.task_results_before)

        if completed_phase >= 2 and result.all_candidates:
            self._w._universal_table.set_candidates(result.all_candidates)
            self._w._left_tabs.setCurrentWidget(self._w._universal_table)

        if completed_phase >= 3 and result.added_reactions:
            self._w._gapfill_panel.set_partial_result(result)
            self._w._right_tabs.setCurrentWidget(self._w._gapfill_panel)

        self._w._statusbar.showMessage(
            f"Workflow cancelled at Phase {completed_phase}/5 \u2014 Resume available"
        )

    def on_gapfill_error(self, error: str, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        self._w._gapfill_worker = None
        QMessageBox.critical(self._w, "Gap-Fill Error", error)
        self._w._statusbar.showMessage("Gap-fill failed")

    def on_apply_gapfill(self) -> None:
        """Apply gap-fill results to the current model display."""
        if self._w._model:
            self._w._reaction_table.set_model_data(self._w._model)
            self._w._overview.set_model(self._w._model)
            self._w._mark_dirty()
            self._w._statusbar.showMessage("Gap-fill results applied to model")

    def load_universal_model(self) -> None:
        """Load a universal model for browsing."""
        if not self._w._model:
            QMessageBox.warning(self._w, "No Model", "Load an SBML model first.")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self._w,
            "Load Universal Model",
            "",
            "Model Files (*.json *.xml *.sbml);;All Files (*)",
        )
        if not filepath:
            return

        from src.core.universal_loader import UniversalLoader

        try:
            loader = UniversalLoader()
            universal_model = loader.load(filepath)
            self._w._loaded_universal_path = filepath

            candidates = loader.extract_candidates(universal_model, self._w._model)

            total = len(universal_model.reactions)
            excluded = total - len(candidates)

            self._w._overview.set_universal_info(
                model_id=universal_model.id,
                total_reactions=total,
                excluded=excluded,
                candidates=len(candidates),
            )

            self._w._universal_table.set_mode("browse")
            self._w._universal_table.set_candidates(candidates)
            self._w._left_tabs.setCurrentWidget(self._w._universal_table)

            self._w._statusbar.showMessage(
                f"Universal model loaded: {len(candidates)} candidate reactions"
            )
        except Exception as e:
            QMessageBox.critical(self._w, "Load Error", str(e))

    def on_universal_selected(self, reaction_id: str) -> None:
        """Handle universal reaction selection — show in detail panel (read-only)."""
        for candidate in self._w._universal_table.get_candidates():
            if candidate.reaction.id == reaction_id:
                self._w._reaction_detail.set_read_only(True)
                self._w._reaction_detail.set_reaction(candidate.reaction)
                break

    def evaluate_universal_candidates(self, candidates: list) -> None:
        """Evaluate selected universal candidates with evidence engine."""
        if not self._w._engine:
            QMessageBox.warning(self._w, "No Engine", "Evidence engine not initialized.")
            return

        reactions = [c.reaction for c in candidates]
        self._w._eval_ctrl.evaluate_batch(reactions)
