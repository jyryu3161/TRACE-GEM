"""Background workers for async operations in the GUI."""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from contextlib import suppress

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.models import CandidateReaction, GapFillResult, ModelData, Reaction
from src.evidence.engine import EvidenceEngine
from src.utils.config import Config

TYPE_CHECKING = False
if TYPE_CHECKING:
    from src.cache.cache_manager import CacheManager
    from src.core.mapping_data import MappingData

logger = logging.getLogger("gem_evaluator.workers")


def _safe_emit(signal, *args) -> None:
    """Emit a signal, silently ignoring RuntimeError if the source was deleted."""
    with suppress(RuntimeError):
        signal.emit(*args)


class WorkerSignals(QObject):
    """Signals for background worker communication."""

    started = Signal()
    progress = Signal(int, int, str)  # current, total, reaction_id
    result = Signal(object)  # ReactionEvidence or dict
    error = Signal(str)
    finished = Signal()


class GapFillWorkerSignals(QObject):
    """Signals for gap-fill workflow with phase-aware progress."""

    started = Signal()
    progress = Signal(str, int, int, str)  # phase, current, total, detail
    result = Signal(object)  # GapFillResult
    cancelled = Signal(object, int)  # (GapFillResult, completed_phase)
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
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            # asyncio.set_event_loop removed (deprecated in Python 3.12+)
            try:
                result = loop.run_until_complete(self.engine.evaluate_reaction(self.reaction))
                _safe_emit(self.signals.result, result)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Worker error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


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
        self._cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()

            def on_progress(current: int, total: int, rxn_id: str) -> None:
                _safe_emit(self.signals.progress, current, total, rxn_id)

            try:
                results = loop.run_until_complete(
                    self.engine.evaluate_batch(
                        self.reactions,
                        progress_callback=on_progress,
                        cancel_event=self._cancel_event,
                    )
                )
                _safe_emit(self.signals.result, results)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Batch worker error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class InitEngineWorker(QRunnable):
    """Worker to initialize the evidence engine."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            # asyncio.set_event_loop removed (deprecated in Python 3.12+)
            try:
                engine = EvidenceEngine(self.config)
                loop.run_until_complete(engine.initialize())
                _safe_emit(self.signals.result, engine)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Init engine error: %s", e)
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class CloseEngineWorker(QRunnable):
    """Worker to close the evidence engine cleanly."""

    def __init__(self, engine: EvidenceEngine) -> None:
        super().__init__()
        self.engine = engine
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            # asyncio.set_event_loop removed (deprecated in Python 3.12+)
            try:
                loop.run_until_complete(self.engine.close())
                _safe_emit(self.signals.result, True)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Close engine error: %s", e)
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class LoadModelWorker(QRunnable):
    """Worker to load an SBML model file."""

    def __init__(self, filepath: str) -> None:
        super().__init__()
        self.filepath = filepath
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            from src.core.sbml_parser import SBMLParser

            parser = SBMLParser()
            model = parser.load_model(self.filepath)
            _safe_emit(self.signals.result, model)
        except Exception as e:
            logger.error("Load model error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class GapFillWorkflowWorker(QRunnable):
    """Worker for the full gap-filling workflow pipeline.

    Steps:
    1. Load universal model
    2. Extract candidates
    3. Parse metabolic tasks
    4. Optionally evaluate candidates with evidence engine
    5. Run GapFillEngine pipeline
    """

    def __init__(
        self,
        config: Config,
        model_data: ModelData,
        universal_path: str,
        task_path: str | None,
        evidence_engine: EvidenceEngine | None,
        options: dict,
        start_phase: int = 1,
        preloaded_before: list | None = None,
        preloaded_candidates: list[CandidateReaction] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.model_data = model_data
        self.universal_path = universal_path
        self.task_path = task_path
        self.evidence_engine = evidence_engine
        self.options = options
        self._start_phase = start_phase
        self._preloaded_before = preloaded_before
        self._preloaded_candidates = preloaded_candidates
        self._cancel_event = threading.Event()
        self.signals = GapFillWorkerSignals()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        """Request pipeline cancellation."""
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(self._run_pipeline())
                if isinstance(result, GapFillResult) and result.is_partial:
                    _safe_emit(self.signals.cancelled, result, result.completed_phase)
                else:
                    _safe_emit(self.signals.result, result)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Gap-fill workflow error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    async def _run_pipeline(self) -> object:
        from src.core.task_parser import TaskParser
        from src.core.universal_loader import UniversalLoader
        from src.gapfill.engine import GapFillEngine

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            _safe_emit(self.signals.progress, phase, current, total, detail)

        # Step 1: Load universal model
        on_progress("loading", 0, 1, "Loading universal model...")
        loader = UniversalLoader()
        universal_model = loader.load(self.universal_path)
        on_progress("loading", 1, 1, "Universal model loaded")

        if self._is_cancelled():
            return GapFillResult(total_tasks=0, is_partial=True, completed_phase=0)

        # Step 2: Extract candidates (or use preloaded)
        if self._preloaded_candidates:
            candidates = self._preloaded_candidates
            on_progress("extracting", 1, 1, f"{len(candidates)} candidates (resumed)")
        else:
            on_progress("extracting", 0, 1, "Extracting candidates...")
            candidates = loader.extract_candidates(universal_model, self.model_data)
            on_progress("extracting", 1, 1, f"{len(candidates)} candidates extracted")

        if self._is_cancelled():
            return GapFillResult(total_tasks=0, is_partial=True, completed_phase=0)

        # Step 3: Parse tasks
        tasks = []
        if self.task_path:
            if self.task_path == "__preloaded__":
                tasks = list(self.options.get("preloaded_tasks") or [])
                on_progress("parsing_tasks", 1, 1, f"{len(tasks)} pre-loaded tasks")
            else:
                on_progress("parsing_tasks", 0, 1, "Parsing metabolic tasks...")
                parser = TaskParser()
                tasks = parser.parse(self.task_path)
                on_progress("parsing_tasks", 1, 1, f"{len(tasks)} tasks parsed")

        if self._is_cancelled():
            return GapFillResult(total_tasks=len(tasks), is_partial=True, completed_phase=0)

        # Step 4: Evaluate candidates (optional, skip on resume)
        evidence_results: dict = {}
        defer_candidate_evidence = False
        if (
            self._start_phase <= 1
            and self.options.get("evaluate_candidates")
            and self.evidence_engine
        ):
            eager_limit = max(0, self.config.candidate_evidence_eager_limit)
            defer_candidate_evidence = eager_limit > 0 and len(candidates) > eager_limit
            if defer_candidate_evidence:
                on_progress(
                    "evaluating",
                    0,
                    len(candidates),
                    (
                        f"{len(candidates)} candidates exceeds eager evidence limit "
                        f"({eager_limit}); deferring evidence to gap-filled reactions"
                    ),
                )
            else:
                on_progress("evaluating", 0, len(candidates), "Evaluating candidates...")

                def eval_progress(current: int, total: int, rxn_id: str) -> None:
                    _safe_emit(self.signals.progress, "evaluating", current, total, rxn_id)

                evidence_results = await self.evidence_engine.evaluate_candidates_batch(
                    candidates, progress_callback=eval_progress
                )

        if self._is_cancelled():
            return GapFillResult(total_tasks=len(tasks), is_partial=True, completed_phase=0)

        # Step 5: Run gap-fill engine
        cobra_model = self.model_data.cobra_model
        if cobra_model is None:
            raise RuntimeError("No cobra model available on ModelData")

        engine = GapFillEngine(self.config)
        organism_code = self.model_data.kegg_organism_code or self.config.kegg_organism_code
        cache_mgr = self.evidence_engine.cache_manager if self.evidence_engine else None
        mapping_data = self.evidence_engine.mapping_data if self.evidence_engine else None
        await engine.initialize(
            organism_code=organism_code,
            cache_manager=cache_mgr,
            mapping_data=mapping_data,
        )
        try:
            result = await engine.run(
                user_model=cobra_model,
                universal_model=universal_model,
                candidates=candidates,
                tasks=tasks,
                evidence_results=evidence_results,
                progress_callback=on_progress,
                cancel_event=self._cancel_event,
                start_phase=self._start_phase,
                preloaded_before=self._preloaded_before,
            )
        finally:
            await engine.close()

        if (
            defer_candidate_evidence
            and self.evidence_engine
            and isinstance(result, GapFillResult)
            and result.added_reactions
        ):
            on_progress(
                "evaluating",
                0,
                len(result.added_reactions),
                "Evaluating gap-filled reactions...",
            )

            def added_eval_progress(current: int, total: int, rxn_id: str) -> None:
                _safe_emit(self.signals.progress, "evaluating", current, total, rxn_id)

            added_evidence = await self.evidence_engine.evaluate_candidates_batch(
                result.added_reactions,
                progress_callback=added_eval_progress,
                cancel_event=self._cancel_event,
            )
            result.added_reactions.sort(
                key=lambda c: (
                    added_evidence[c.reaction.id].confidence_score
                    if c.reaction.id in added_evidence
                    else 0.0
                ),
                reverse=True,
            )

        return result


class EvaluateCandidatesWorker(QRunnable):
    """Worker to evaluate candidate reactions with the evidence engine."""

    def __init__(
        self,
        engine: EvidenceEngine,
        candidates: list[CandidateReaction],
    ) -> None:
        super().__init__()
        self.engine = engine
        self.candidates = candidates
        self.signals = WorkerSignals()
        self._cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()

            def on_progress(current: int, total: int, rxn_id: str) -> None:
                _safe_emit(self.signals.progress, current, total, rxn_id)

            try:
                results = loop.run_until_complete(
                    self.engine.evaluate_candidates_batch(
                        self.candidates,
                        progress_callback=on_progress,
                        cancel_event=self._cancel_event,
                    )
                )
                _safe_emit(self.signals.result, results)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Evaluate candidates error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class TaskRunWorker(QRunnable):
    """Worker to run metabolic tasks in background with progress reporting."""

    def __init__(self, cobra_model: object, tasks: list) -> None:
        super().__init__()
        self.cobra_model = cobra_model
        self.tasks = tasks
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            from src.core.task_parser import TaskRunner

            runner = TaskRunner()

            def on_progress(current: int, total: int, detail: str) -> None:
                _safe_emit(self.signals.progress, current, total, detail)

            results = runner.run_all(self.cobra_model, self.tasks, on_progress)
            _safe_emit(self.signals.result, results)
        except Exception as e:
            logger.error("Task run error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class OrganismFilterWorker(QRunnable):
    """Worker to run organism-specificity filtering on candidates."""

    def __init__(
        self,
        organism_code: str,
        candidates: list[CandidateReaction],
        cache_manager: CacheManager | None = None,
        mapping_data: MappingData | None = None,
    ) -> None:
        super().__init__()
        self.organism_code = organism_code
        self.candidates = candidates
        self.cache_manager = cache_manager
        self.mapping_data = mapping_data
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            # asyncio.set_event_loop removed (deprecated in Python 3.12+)
            try:
                result = loop.run_until_complete(self._run_filter())
                _safe_emit(self.signals.result, result)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Organism filter error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)

    async def _run_filter(self) -> list[CandidateReaction]:
        from src.gapfill.organism_filter import OrganismFilter

        def on_progress(current: int, total: int, rxn_id: str) -> None:
            _safe_emit(self.signals.progress, current, total, rxn_id)

        filt = OrganismFilter(
            organism_code=self.organism_code,
            cache_manager=self.cache_manager,
            mapping_data=self.mapping_data,
        )
        await filt.initialize()
        try:
            result = await filt.filter_candidates(
                self.candidates, progress_callback=on_progress
            )
        finally:
            await filt.close()
        return result
