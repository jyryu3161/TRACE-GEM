"""Tests for GUI worker signals and error handling."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import (
    CandidateReaction,
    EvaluationStatus,
    GapFillResult,
    MetabolicTask,
    ModelData,
    Reaction,
    ReactionEvidence,
)
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

# Only create QApplication if GUI is available (avoids SIGABRT)
if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)


class TestWorkerSignals:
    def test_signals_instantiation(self):
        from src.gui.workers import WorkerSignals

        signals = WorkerSignals()
        assert signals is not None


class TestEvaluateReactionWorker:
    def test_instantiation(self):
        from src.gui.workers import EvaluateReactionWorker

        engine = MagicMock()
        rxn = Reaction(id="ENO", name="enolase", equation="a -> b")
        worker = EvaluateReactionWorker(engine, rxn)
        assert worker.engine is engine
        assert worker.reaction is rxn

    def test_run_success(self):
        from src.gui.workers import EvaluateReactionWorker

        ev = ReactionEvidence(reaction_id="ENO")
        ev.status = EvaluationStatus.EVALUATED

        engine = MagicMock()
        engine.evaluate_reaction = AsyncMock(return_value=ev)

        rxn = Reaction(id="ENO", name="enolase", equation="a -> b")
        worker = EvaluateReactionWorker(engine, rxn)

        results = []
        errors = []
        finished = []
        worker.signals.result.connect(lambda r: results.append(r))
        worker.signals.error.connect(lambda e: errors.append(e))
        worker.signals.finished.connect(lambda: finished.append(True))

        worker.run()

        assert len(results) == 1
        assert results[0].reaction_id == "ENO"
        assert len(errors) == 0
        assert len(finished) == 1

    def test_run_error(self):
        from src.gui.workers import EvaluateReactionWorker

        engine = MagicMock()
        engine.evaluate_reaction = AsyncMock(side_effect=RuntimeError("API down"))

        rxn = Reaction(id="ENO", name="enolase", equation="a -> b")
        worker = EvaluateReactionWorker(engine, rxn)

        errors = []
        worker.signals.error.connect(lambda e: errors.append(e))

        worker.run()

        assert len(errors) == 1
        assert "API down" in errors[0]


class TestEvaluateBatchWorker:
    def test_instantiation(self):
        from src.gui.workers import EvaluateBatchWorker

        engine = MagicMock()
        reactions = [Reaction(id="R1", name="R1", equation="a -> b")]
        worker = EvaluateBatchWorker(engine, reactions)
        assert worker.engine is engine
        assert len(worker.reactions) == 1

    def test_cancel(self):
        from src.gui.workers import EvaluateBatchWorker

        engine = MagicMock()
        worker = EvaluateBatchWorker(engine, [])
        # cancel before run should not raise
        worker.cancel()


class TestInitEngineWorker:
    def test_instantiation(self):
        from src.gui.workers import InitEngineWorker
        from src.utils.config import Config

        config = Config()
        worker = InitEngineWorker(config)
        assert worker.config is config


class TestLoadModelWorker:
    def test_instantiation(self):
        from src.gui.workers import LoadModelWorker

        worker = LoadModelWorker("/path/to/model.xml")
        assert worker.filepath == "/path/to/model.xml"

    def test_run_error_for_missing_file(self):
        from src.gui.workers import LoadModelWorker

        worker = LoadModelWorker("/nonexistent/model.xml")
        errors = []
        worker.signals.error.connect(lambda e: errors.append(e))

        worker.run()

        assert len(errors) == 1


class TestGapFillWorkflowWorker:
    async def test_default_evaluates_all_candidate_evidence(self, monkeypatch):
        from src.gui.workers import GapFillWorkflowWorker
        from src.utils.config import Config

        candidates = [
            CandidateReaction(Reaction(id="R1", name="R1", equation="a -> b")),
            CandidateReaction(Reaction(id="R2", name="R2", equation="a -> b")),
        ]
        captured: dict[str, object] = {}

        class FakeLoader:
            def load(self, path):
                return object()

            def extract_candidates(self, universal_model, model_data, **kwargs):
                return candidates

        class FakeGapFillEngine:
            def __init__(self, config):
                pass

            async def initialize(self, **kwargs):
                pass

            async def run(self, **kwargs):
                captured["evidence_results"] = kwargs["evidence_results"]
                result = GapFillResult(total_tasks=0)
                result.all_candidates = candidates
                result.added_reactions = []
                result.task_results_before = []
                result.task_results_after = []
                return result

            async def close(self):
                pass

        import src.core.universal_loader as universal_loader_module
        import src.gapfill.engine as gapfill_engine_module

        monkeypatch.setattr(universal_loader_module, "UniversalLoader", FakeLoader)
        monkeypatch.setattr(gapfill_engine_module, "GapFillEngine", FakeGapFillEngine)

        evidence = MagicMock()
        evidence.cache_manager = None
        evidence.mapping_data = None
        evidence.evaluate_candidates_batch = AsyncMock(
            return_value={
                "R1": ReactionEvidence(reaction_id="R1", confidence_score=0.8),
                "R2": ReactionEvidence(reaction_id="R2", confidence_score=0.7),
            }
        )

        worker = GapFillWorkflowWorker(
            config=Config(),
            model_data=ModelData(id="m", name="m", cobra_model=object()),
            universal_path="universal.json",
            task_path=None,
            evidence_engine=evidence,
            options={"evaluate_candidates": True},
        )

        await worker._run_pipeline()

        evidence.evaluate_candidates_batch.assert_awaited_once()
        evaluated_candidates = evidence.evaluate_candidates_batch.await_args.args[0]
        assert evaluated_candidates == candidates
        assert sorted(captured["evidence_results"]) == ["R1", "R2"]

    async def test_large_candidate_set_defers_evidence_to_added_reactions(self, monkeypatch):
        from src.gui.workers import GapFillWorkflowWorker
        from src.utils.config import Config

        candidates = [
            CandidateReaction(Reaction(id="R1", name="R1", equation="a -> b")),
            CandidateReaction(Reaction(id="R2", name="R2", equation="a -> b")),
        ]
        added = [candidates[1]]
        captured: dict[str, object] = {}

        class FakeLoader:
            def load(self, path):
                return object()

            def extract_candidates(self, universal_model, model_data, **kwargs):
                return candidates

        class FakeParser:
            def parse(self, path):
                raise AssertionError("preloaded tasks should not be parsed from disk")

        class FakeGapFillEngine:
            def __init__(self, config):
                pass

            async def initialize(self, **kwargs):
                pass

            async def run(self, **kwargs):
                captured["tasks"] = kwargs["tasks"]
                captured["evidence_results"] = kwargs["evidence_results"]
                result = GapFillResult(total_tasks=len(kwargs["tasks"]))
                result.all_candidates = candidates
                result.added_reactions = list(added)
                result.task_results_before = []
                result.task_results_after = []
                return result

            async def close(self):
                pass

        import src.core.task_parser as task_parser_module
        import src.core.universal_loader as universal_loader_module
        import src.gapfill.engine as gapfill_engine_module

        monkeypatch.setattr(universal_loader_module, "UniversalLoader", FakeLoader)
        monkeypatch.setattr(task_parser_module, "TaskParser", FakeParser)
        monkeypatch.setattr(gapfill_engine_module, "GapFillEngine", FakeGapFillEngine)

        evidence = MagicMock()
        evidence.cache_manager = None
        evidence.mapping_data = None
        evidence.evaluate_candidates_batch = AsyncMock(
            return_value={"R2": ReactionEvidence(reaction_id="R2", confidence_score=1.0)}
        )

        task = MetabolicTask(task_id="T1", task_type="Metabolite", target_id="atp_c")
        config = Config(candidate_evidence_eager_limit=1)
        worker = GapFillWorkflowWorker(
            config=config,
            model_data=ModelData(id="m", name="m", cobra_model=object()),
            universal_path="universal.json",
            task_path="__preloaded__",
            evidence_engine=evidence,
            options={
                "evaluate_candidates": True,
                "preloaded_tasks": [task],
            },
        )

        result = await worker._run_pipeline()

        assert result.added_reactions == added
        assert captured["tasks"] == [task]
        assert captured["evidence_results"] == {}
        evidence.evaluate_candidates_batch.assert_awaited_once()
        evaluated_candidates = evidence.evaluate_candidates_batch.await_args.args[0]
        assert evaluated_candidates == added
