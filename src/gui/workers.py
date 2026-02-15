"""Background workers for async operations in the GUI."""

from __future__ import annotations

import asyncio
import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.models import Reaction
from src.evidence.engine import EvidenceEngine
from src.utils.config import Config

logger = logging.getLogger("gem_evaluator.workers")


class WorkerSignals(QObject):
    """Signals for background worker communication."""

    started = Signal()
    progress = Signal(int, int, str)  # current, total, reaction_id
    result = Signal(object)  # ReactionEvidence or dict
    error = Signal(str)
    finished = Signal()


class EvaluateReactionWorker(QRunnable):
    """Worker to evaluate a single reaction in the background."""

    def __init__(self, engine: EvidenceEngine, reaction: Reaction) -> None:
        super().__init__()
        self.engine = engine
        self.reaction = reaction
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.engine.evaluate_reaction(self.reaction))
                self.signals.result.emit(result)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Worker error: %s\n%s", e, traceback.format_exc())
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class EvaluateBatchWorker(QRunnable):
    """Worker to evaluate multiple reactions in batch."""

    def __init__(
        self,
        engine: EvidenceEngine,
        reactions: list[Reaction],
    ) -> None:
        super().__init__()
        self.engine = engine
        self.reactions = reactions
        self.signals = WorkerSignals()
        self._cancel_event: asyncio.Event | None = None
        self.setAutoDelete(True)

    def cancel(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._cancel_event = asyncio.Event()

            def on_progress(current: int, total: int, rxn_id: str) -> None:
                self.signals.progress.emit(current, total, rxn_id)

            try:
                results = loop.run_until_complete(
                    self.engine.evaluate_batch(
                        self.reactions,
                        progress_callback=on_progress,
                        cancel_event=self._cancel_event,
                    )
                )
                self.signals.result.emit(results)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Batch worker error: %s\n%s", e, traceback.format_exc())
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class InitEngineWorker(QRunnable):
    """Worker to initialize the evidence engine."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                engine = EvidenceEngine(self.config)
                loop.run_until_complete(engine.initialize())
                self.signals.result.emit(engine)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Init engine error: %s", e)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class CloseEngineWorker(QRunnable):
    """Worker to close the evidence engine cleanly."""

    def __init__(self, engine: EvidenceEngine) -> None:
        super().__init__()
        self.engine = engine
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.engine.close())
                self.signals.result.emit(True)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Close engine error: %s", e)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class LoadModelWorker(QRunnable):
    """Worker to load an SBML model file."""

    def __init__(self, filepath: str) -> None:
        super().__init__()
        self.filepath = filepath
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            from src.core.sbml_parser import SBMLParser

            parser = SBMLParser()
            model = parser.load_model(self.filepath)
            self.signals.result.emit(model)
        except Exception as e:
            logger.error("Load model error: %s", e)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
