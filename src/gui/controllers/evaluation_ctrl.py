"""Evaluation controller — manages candidate evidence evaluation lifecycle.

Evidence is KEGG-only and computed ONLY for gap-fill candidate reactions; there
is no per-reaction evaluation of the loaded model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from src.gui.progress_dialog import ProgressDialog
from src.gui.workers import EvaluateCandidatesWorker

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.evaluation")


class EvaluationController:
    """Manages candidate evidence evaluation lifecycle."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def run_candidate_evaluation(self, candidates: list) -> None:
        """Evaluate universal candidate reactions with the evidence engine."""
        engine = self._w._engine
        if engine is None:
            QMessageBox.warning(self._w, "Evidence Engine", "Evidence engine is not initialized.")
            return
        dialog = ProgressDialog("Evaluating Universal Candidates", self._w)

        worker = EvaluateCandidatesWorker(engine, candidates)
        self._w._batch_worker = worker

        worker.signals.progress.connect(dialog.update_progress)
        worker.signals.result.connect(lambda r: self.on_candidate_batch_complete(r, dialog))
        worker.signals.error.connect(lambda e: self.on_batch_error(e, dialog))
        dialog.cancelled.connect(worker.cancel)

        self._w._thread_pool.start(worker)
        dialog.exec()

    def on_candidate_batch_complete(self, results: object, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        if isinstance(results, dict):
            # Update universal candidate table
            self._w._universal_table._model.set_evidence(results)

            # Update right panel if a candidate reaction is currently selected
            detail_rxn = self._w._reaction_detail._reaction
            current_rxn = detail_rxn.id if detail_rxn else None
            if current_rxn and current_rxn in results:
                ev = results[current_rxn]
                self._w._reaction_detail.update_evidence(ev)
                self._w._evidence_panel.set_evidence(ev)
        self._w._statusbar.showMessage("Candidate evaluation complete")
        self._w._batch_worker = None

    def on_batch_error(self, error: str, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        QMessageBox.warning(self._w, "Evaluation Error", error)
        self._w._batch_worker = None
