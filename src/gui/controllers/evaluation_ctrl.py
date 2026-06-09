"""Evaluation controller — manages evidence evaluation lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from src.core.models import ReactionEvidence
from src.gui.progress_dialog import ProgressDialog
from src.gui.workers import EvaluateBatchWorker, EvaluateReactionWorker

if TYPE_CHECKING:
    from src.core.models import Reaction
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.evaluation")


class EvaluationController:
    """Manages evidence evaluation lifecycle."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def evaluate_selected(self) -> None:
        """Evaluate currently selected reaction."""
        rxn = self._w._get_selected_reaction()
        if rxn:
            self.evaluate_reaction(rxn)

    def evaluate_reaction_by_id(self, reaction_id: str) -> None:
        # Try model reactions first
        if self._w._model:
            rxn = self._w._model.get_reaction(reaction_id)
            if rxn:
                self.evaluate_reaction(rxn)
                return

        # Try universal candidates
        for candidate in self._w._universal_table.get_candidates():
            if candidate.reaction.id == reaction_id:
                self.evaluate_reaction(candidate.reaction)
                return

    def evaluate_reaction(self, reaction: Reaction) -> None:
        if not self._w._engine:
            if self._w._engine_error:
                QMessageBox.warning(
                    self._w,
                    "Engine Error",
                    f"Evidence engine initialization failed: {self._w._engine_error}",
                )
            elif self._w._engine_init_in_progress or self._w._engine_close_in_progress:
                QMessageBox.warning(self._w, "Not Ready", "Evidence engine is still initializing.")
            else:
                self._w._init_engine()
                QMessageBox.warning(
                    self._w,
                    "Not Ready",
                    "Evidence engine is not ready yet. Initialization has been retried.",
                )
            return

        self._w._statusbar.showMessage(f"Evaluating {reaction.id}...")
        worker = EvaluateReactionWorker(self._w._engine, reaction)
        worker.signals.result.connect(self.on_reaction_evaluated)
        worker.signals.error.connect(
            lambda e: self._w._statusbar.showMessage(f"Evaluation error: {e}")
        )
        self._w._thread_pool.start(worker)

    def on_reaction_evaluated(self, evidence: object) -> None:
        if not isinstance(evidence, ReactionEvidence):
            return

        self._w._reaction_table.update_evidence(evidence.reaction_id, evidence)
        self._w._reaction_detail.update_evidence(evidence)
        self._w._evidence_panel.set_evidence(evidence)

        # Also update universal candidate table if it has this reaction
        if self._w._engine:
            self._w._universal_table._model.set_evidence(
                self._w._engine.get_all_results()
            )

        self._w._update_eval_count()
        self._w._statusbar.showMessage(
            f"Evaluated {evidence.reaction_id} — Evidence: {evidence.evidence_tier.label}"
        )

    def evaluate_all(self) -> None:
        if not self._w._model or not self._w._engine:
            QMessageBox.warning(self._w, "Not Ready", "Load a model and wait for engine init.")
            return

        scope_dialog = QDialog(self._w)
        scope_dialog.setWindowTitle("Evaluate All — Select Scope")
        scope_dialog.setMinimumWidth(360)
        dlg_layout = QVBoxLayout(scope_dialog)

        dlg_layout.addWidget(QLabel("Select which reactions to evaluate:"))

        model_count = len(self._w._model.reactions)
        eval_model_cb = QCheckBox(f"Model Reactions ({model_count} reactions)")
        eval_model_cb.setChecked(True)
        dlg_layout.addWidget(eval_model_cb)

        candidates = self._w._universal_table.get_candidates()
        has_candidates = bool(candidates)
        cand_count = len(candidates) if candidates else 0
        eval_candidates_cb = QCheckBox(
            f"Universal Model Reactions ({cand_count} candidates)"
        )
        eval_candidates_cb.setEnabled(has_candidates)
        eval_candidates_cb.setChecked(False)
        dlg_layout.addWidget(eval_candidates_cb)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(scope_dialog.accept)
        btn_box.rejected.connect(scope_dialog.reject)
        dlg_layout.addWidget(btn_box)

        if scope_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        do_model = eval_model_cb.isChecked()
        do_candidates = eval_candidates_cb.isChecked()

        if not do_model and not do_candidates:
            return

        if do_model:
            self.run_model_evaluation(do_candidates, candidates)
        elif do_candidates and candidates:
            self.run_candidate_evaluation(candidates)

    def run_model_evaluation(
        self, also_candidates: bool, candidates: list | None
    ) -> None:
        """Evaluate model reactions, then optionally candidates."""
        reactions = self._w._model.reactions
        dialog = ProgressDialog("Evaluating Model Reactions", self._w)

        worker = EvaluateBatchWorker(self._w._engine, reactions)
        self._w._batch_worker = worker

        def on_complete(results: object) -> None:
            self.on_batch_complete(results, dialog)
            if also_candidates and candidates:
                self.run_candidate_evaluation(candidates)

        worker.signals.progress.connect(dialog.update_progress)
        worker.signals.result.connect(on_complete)
        worker.signals.error.connect(lambda e: self.on_batch_error(e, dialog))
        dialog.cancelled.connect(worker.cancel)

        self._w._thread_pool.start(worker)
        dialog.exec()

    def run_candidate_evaluation(self, candidates: list) -> None:
        """Evaluate universal candidate reactions."""
        reactions = [c.reaction for c in candidates]
        dialog = ProgressDialog("Evaluating Universal Candidates", self._w)

        worker = EvaluateBatchWorker(self._w._engine, reactions)
        self._w._batch_worker = worker

        worker.signals.progress.connect(dialog.update_progress)
        worker.signals.result.connect(
            lambda r: self.on_candidate_batch_complete(r, dialog)
        )
        worker.signals.error.connect(lambda e: self.on_batch_error(e, dialog))
        dialog.cancelled.connect(worker.cancel)

        self._w._thread_pool.start(worker)
        dialog.exec()

    def on_candidate_batch_complete(
        self, results: object, dialog: ProgressDialog
    ) -> None:
        dialog.set_complete()
        if isinstance(results, dict):
            # Update both model table and universal candidate table
            self._w._reaction_table.update_all_evidence(results)
            self._w._universal_table._model.set_evidence(results)
            self._w._update_charts()

            # Update right panel if a candidate reaction is currently selected
            detail_rxn = self._w._reaction_detail._reaction
            current_rxn = detail_rxn.id if detail_rxn else None
            if current_rxn and current_rxn in results:
                ev = results[current_rxn]
                self._w._reaction_detail.update_evidence(ev)
                self._w._evidence_panel.set_evidence(ev)
        self._w._update_eval_count()
        self._w._statusbar.showMessage("Candidate evaluation complete")
        self._w._batch_worker = None

    def on_batch_complete(self, results: object, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        if isinstance(results, dict):
            self._w._reaction_table.update_all_evidence(results)
            self._w._update_charts()
        self._w._update_eval_count()
        self._w._statusbar.showMessage("Batch evaluation complete")
        self._w._batch_worker = None

    def on_batch_error(self, error: str, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        QMessageBox.warning(self._w, "Evaluation Error", error)
        self._w._batch_worker = None

    def clear_results(self) -> None:
        if self._w._engine:
            self._w._engine.clear_results()
        self._w._evidence_panel.clear()
        if self._w._model:
            self._w._reaction_table.set_model_data(self._w._model)
        self._w._update_eval_count()
        self._w._statusbar.showMessage("Results cleared")

    def evaluate_batch(self, reactions: list) -> None:
        """Run batch evaluation on a list of reactions."""
        if not self._w._engine:
            return

        dialog = ProgressDialog("Evaluating Reactions", self._w)

        worker = EvaluateBatchWorker(self._w._engine, reactions)
        self._w._batch_worker = worker

        worker.signals.progress.connect(dialog.update_progress)
        worker.signals.result.connect(lambda r: self.on_batch_complete(r, dialog))
        worker.signals.error.connect(lambda e: self.on_batch_error(e, dialog))
        dialog.cancelled.connect(worker.cancel)

        self._w._thread_pool.start(worker)
        dialog.exec()
