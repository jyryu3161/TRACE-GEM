"""Tests for GUI worker signals and error handling."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import (
    EvaluationStatus,
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
