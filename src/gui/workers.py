"""Background workers for async operations in the GUI."""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.models import CandidateReaction, GapFillResult, ModelData, Reaction
from src.evidence.engine import EvidenceEngine
from src.utils.config import Config

if TYPE_CHECKING:
    import cobra

    from src.build.carveme_runner import CarveMeOptions
    from src.cache.cache_manager import CacheManager
    from src.core.mapping_data import MappingData

logger = logging.getLogger("metataskgapfill.workers")


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
                result = loop.run_until_complete(
                    self.engine.evaluate_candidate(CandidateReaction(reaction=self.reaction))
                )
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
                    self.engine.evaluate_candidates_batch(
                        [CandidateReaction(reaction=reaction) for reaction in self.reactions],
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
        preloaded_result: GapFillResult | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.model_data = model_data
        self.universal_path = universal_path
        self.task_path = task_path
        self.evidence_engine = evidence_engine
        self.options = options
        self._start_phase = start_phase
        self._preloaded_result = preloaded_result
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

        checkpoint = self._preloaded_result or GapFillResult()
        if checkpoint.working_model is not None:
            working_model = cast("cobra.Model", checkpoint.working_model)
        else:
            source_model = self.model_data.cobra_model
            if source_model is None:
                raise RuntimeError("No cobra model available on ModelData")
            working_model = source_model.copy()
            checkpoint.working_model = working_model

        def partial_result(total_tasks: int = 0) -> GapFillResult:
            checkpoint.total_tasks = total_tasks
            checkpoint.is_partial = True
            checkpoint.working_model = working_model
            return checkpoint

        # Step 1: Load universal model
        on_progress("loading", 0, 1, "Loading universal model...")
        loader = UniversalLoader()
        universal_model = loader.load(self.universal_path)
        exclude_exchange_gapfill = bool(self.options.get("exclude_exchange_gapfill", True))
        self.config.gapfill_exclude_exchange_reactions = exclude_exchange_gapfill
        on_progress("loading", 1, 1, "Universal model loaded")

        if self._is_cancelled():
            return partial_result()

        # Step 2: Extract candidates (or use preloaded)
        if checkpoint.all_candidates:
            candidates = checkpoint.all_candidates
            on_progress("extracting", 1, 1, f"{len(candidates)} candidates (resumed)")
        else:
            on_progress("extracting", 0, 1, "Extracting candidates...")
            candidates = loader.extract_candidates(
                universal_model,
                self.model_data,
                exclude_exchange_reactions=exclude_exchange_gapfill,
            )
            checkpoint.all_candidates = list(candidates)
            on_progress("extracting", 1, 1, f"{len(candidates)} candidates extracted")

        if self._is_cancelled():
            return partial_result()

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

        # Merge an EXPLICIT base medium only if one was provided (parity with the
        # CLI --medium). Tasks otherwise use only their explicit file-declared
        # background/task medium; never merge the model's default medium.
        medium_arg = self.options.get("medium")
        if medium_arg and tasks:
            from src.cli import load_medium_argument
            from src.gapfill.refine import apply_base_medium_to_tasks

            base_medium = load_medium_argument(medium_arg, working_model)
            tasks = apply_base_medium_to_tasks(tasks, base_medium)

        if self._is_cancelled():
            return partial_result(len(tasks))

        # Step 4: Evaluate candidates (optional, skip on resume)
        evidence_results = dict(checkpoint.evidence_results)
        if (
            self._start_phase <= 1
            and not evidence_results
            and self.options.get("evaluate_candidates")
            and self.evidence_engine
        ):
            on_progress("evaluating", 0, len(candidates), "Evaluating candidates...")

            def eval_progress(current: int, total: int, rxn_id: str) -> None:
                _safe_emit(self.signals.progress, "evaluating", current, total, rxn_id)

            evidence_results = await self.evidence_engine.evaluate_candidates_batch(
                candidates, progress_callback=eval_progress
            )
            checkpoint.evidence_results = dict(evidence_results)

        if self._is_cancelled():
            return partial_result(len(tasks))

        # Step 5: Run gap-fill engine
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
                user_model=working_model,
                universal_model=universal_model,
                candidates=candidates,
                tasks=tasks,
                evidence_results=evidence_results,
                progress_callback=on_progress,
                cancel_event=self._cancel_event,
                start_phase=self._start_phase,
                preloaded_result=checkpoint,
            )
        finally:
            await engine.close()

        result.working_model = working_model
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
            result = await filt.filter_candidates(self.candidates, progress_callback=on_progress)
        finally:
            await filt.close()
        return result


class BuildWorkerSignals(QObject):
    """Signals for CarveMe model construction workers."""

    started = Signal()
    line = Signal(str)  # raw `carve` stdout line -> build log view
    progress = Signal(int, int, str)  # models_done, models_total, label
    model_built = Signal(object)  # BuildItemResult (batch, per model)
    result = Signal(object)  # BuiltModel (single) or list[BuildItemResult] (batch)
    error = Signal(str)
    finished = Signal()


class BuildModelWorker(QRunnable):
    """Build a single genome-scale model from a protein FASTA with CarveMe.

    The build runs as an external `carve` subprocess (off the GUI thread).
    ``cancel()`` sets an event that the runner polls and uses to terminate the
    live subprocess.
    """

    def __init__(
        self,
        config: Config,
        fasta_path: str,
        kegg_code: str | None,
        options: CarveMeOptions | None = None,
        output_path: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.fasta_path = fasta_path
        self.kegg_code = kegg_code
        self.options = options
        self.output_path = output_path
        self.signals = BuildWorkerSignals()
        self._cancel_event = threading.Event()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            from src.build.build_engine import BuildEngine

            engine = BuildEngine(self.config)

            # Probe the CarveMe toolchain here (worker thread) so its blocking
            # `carve --help`/`diamond --version` subprocesses never freeze the GUI.
            avail = engine.runner.check_available(solver=self.config.carveme_solver)
            if not avail.ok:
                _safe_emit(self.signals.error, "CarveMe toolchain not available:\n" + avail.message)
                return

            def on_line(line: str) -> None:
                _safe_emit(self.signals.line, line)

            built = engine.build_one(
                self.fasta_path,
                self.kegg_code,
                options=self.options,
                output_path=self.output_path,
                on_line=on_line,
                cancel_token=self._cancel_event,
            )
            _safe_emit(self.signals.result, built)
        except Exception as e:
            logger.error("Build model error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)


class BatchBuildWorker(QRunnable):
    """Build several models from a list of BuildJob specs with CarveMe.

    Models are built one at a time (optionally parallel per config); a failure
    in one model does not abort the batch. ``model_built`` fires per genome.
    """

    def __init__(
        self,
        config: Config,
        jobs: list,
        options: CarveMeOptions | None = None,
        output_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.jobs = jobs
        self.options = options
        self.output_dir = output_dir
        self.signals = BuildWorkerSignals()
        self._cancel_event = threading.Event()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            from src.build.build_engine import BuildEngine

            engine = BuildEngine(self.config)
            total = len(self.jobs)

            # Probe toolchain on the worker thread (off the GUI thread).
            avail = engine.runner.check_available(solver=self.config.carveme_solver)
            if not avail.ok:
                _safe_emit(self.signals.error, "CarveMe toolchain not available:\n" + avail.message)
                return

            def on_line(line: str) -> None:
                _safe_emit(self.signals.line, line)

            def on_model_built(index: int, item: object) -> None:
                _safe_emit(self.signals.model_built, item)
                label = getattr(getattr(item, "job", None), "label", str(index + 1))
                _safe_emit(self.signals.progress, index + 1, total, label)

            results = engine.build_batch(
                self.jobs,
                options=self.options,
                output_dir=self.output_dir,
                on_line=on_line,
                on_model_built=on_model_built,
                cancel_token=self._cancel_event,
            )
            _safe_emit(self.signals.result, results)
        except Exception as e:
            logger.error("Batch build error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)
