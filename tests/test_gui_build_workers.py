"""Tests for the GUI CarveMe build workers (BuildEngine is mocked)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.core.models import ModelData
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _carve_available(monkeypatch):
    """Workers probe the CarveMe toolchain; stub it so tests don't need carve."""
    from src.build.carveme_runner import CarveMeAvailability, CarveMeRunner

    monkeypatch.setattr(
        CarveMeRunner,
        "check_available",
        lambda self, solver=None: CarveMeAvailability(carve_ok=True, diamond_ok=True, message="OK"),
    )


def _fake_built(model_id: str = "eco_built", kegg: str = "eco"):
    from src.build.build_engine import BuiltModel
    from src.build.carveme_runner import CarveMeResult

    md = ModelData(id=model_id, name=model_id, reactions=[], metabolites=[], genes=[])
    md.kegg_organism_code = kegg
    return BuiltModel(
        model_data=md,
        sbml_path=Path(f"{model_id}.xml"),
        kegg_code=kegg,
        carve_result=CarveMeResult(fasta_path=Path("g.faa"), output_path=Path(f"{model_id}.xml")),
    )


def test_refine_defers_until_engine_ready() -> None:
    """Build→Refine must wait for the evidence engine to (re)initialize before
    launching gap-fill, so it never runs with a stale/null engine."""
    import time

    from PySide6.QtWidgets import QWidget

    from src.gui.controllers.construct_ctrl import ConstructController

    class _FakeGapfill:
        def __init__(self) -> None:
            self.n = 0

        def start_workflow(self) -> None:
            self.n += 1

    class _FakeWindow(QWidget):  # QWidget so QTimer(self._w) gets a valid parent
        pass

    w = _FakeWindow()
    w._engine = None
    w._engine_init_in_progress = True
    w._pending_engine_init = False
    w._statusbar = type("S", (), {"showMessage": lambda *a, **k: None})()
    w._gapfill_ctrl = _FakeGapfill()

    ctrl = ConstructController(w)
    ctrl._start_refine_when_engine_ready()
    _app.processEvents()
    assert w._gapfill_ctrl.n == 0, "must defer while engine not ready"

    # Engine becomes ready -> the QTimer should fire start_workflow.
    w._engine = object()
    w._engine_init_in_progress = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and w._gapfill_ctrl.n == 0:
        _app.processEvents()
        time.sleep(0.05)
    assert w._gapfill_ctrl.n == 1, "must start gap-fill once engine is ready"
    w.close()


def test_start_single_build_rejects_missing_universe_file(tmp_path, monkeypatch) -> None:
    """GUI must reject a non-existent universe_file early, before any worker starts."""
    from PySide6.QtWidgets import QWidget

    from src.gui.controllers import construct_ctrl as cc_mod
    from src.gui.controllers.construct_ctrl import ConstructController
    from src.utils.config import Config

    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    missing = tmp_path / "missing_universe.xml.gz"

    started: list = []
    warnings: list = []

    class _FakePanel:
        def get_single_spec(self):
            return {"fasta": str(fasta), "universe_file": str(missing), "kegg_code": "eco"}

    class _FakeWindow(QWidget):
        pass

    w = _FakeWindow()
    w._build_panel = _FakePanel()
    w._config = Config()
    w._active_workers = []
    w._thread_pool = type("TP", (), {"start": lambda self, wk: started.append(wk)})()
    monkeypatch.setattr(cc_mod.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    ctrl = ConstructController(w)
    ctrl.start_single_build()
    assert warnings, "missing universe_file should raise a warning dialog"
    assert started == [], "no build worker should start when universe_file is missing"
    w.close()


def test_start_batch_build_rejects_missing_universe_file(tmp_path, monkeypatch) -> None:
    """Batch path rejects a missing per-row universe_file before any worker starts."""
    from PySide6.QtWidgets import QWidget

    from src.gui.controllers import construct_ctrl as cc_mod
    from src.gui.controllers.construct_ctrl import ConstructController
    from src.utils.config import Config

    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    missing = tmp_path / "missing_universe.xml.gz"

    started: list = []
    criticals: list = []

    class _FakePanel:
        def get_batch_jobs(self):
            return [{"fasta": str(fasta), "kegg_code": "eco", "universe_file": str(missing)}]

    class _FakeWindow(QWidget):
        pass

    w = _FakeWindow()
    w._build_panel = _FakePanel()
    w._config = Config()
    w._active_workers = []
    w._thread_pool = type("TP", (), {"start": lambda self, wk: started.append(wk)})()
    monkeypatch.setattr(cc_mod.QMessageBox, "critical", lambda *a, **k: criticals.append(a))

    ctrl = ConstructController(w)
    ctrl.start_batch_build()
    assert criticals, "missing per-row universe_file should raise a critical dialog"
    assert started == [], "no batch worker should start when a universe_file is missing"
    w.close()


def test_build_panel_set_busy_locks_mode_toggle() -> None:
    from src.gui.build_panel import BuildPanelWidget

    bp = BuildPanelWidget()
    bp.set_busy(True)
    assert not bp._single_radio.isEnabled()
    assert not bp._batch_radio.isEnabled()
    assert not bp._build_btn.isEnabled()
    assert bp._cancel_btn.isEnabled()
    bp.set_busy(False)
    assert bp._single_radio.isEnabled()
    assert bp._build_btn.isEnabled()
    assert not bp._cancel_btn.isEnabled()


def test_build_model_worker_success(monkeypatch) -> None:
    from src.gui.workers import BuildModelWorker
    from src.utils.config import Config

    built = _fake_built()

    def fake_build_one(self, fasta_path, kegg_code, options=None, output_path=None,
                       on_line=None, cancel_token=None, label=""):
        if on_line:
            on_line("carve: building...")
        return built

    monkeypatch.setattr("src.build.build_engine.BuildEngine.build_one", fake_build_one)

    worker = BuildModelWorker(Config(), "data/eco_protein.faa", "eco")
    results, lines, errors, finished = [], [], [], []
    worker.signals.result.connect(results.append)
    worker.signals.line.connect(lines.append)
    worker.signals.error.connect(errors.append)
    worker.signals.finished.connect(lambda: finished.append(True))

    worker.run()

    assert results == [built]
    assert "carve: building..." in lines
    assert errors == []
    assert finished == [True]


def test_build_model_worker_error(monkeypatch) -> None:
    from src.gui.workers import BuildModelWorker
    from src.utils.config import Config

    def boom(self, *a, **k):
        raise RuntimeError("carve exploded")

    monkeypatch.setattr("src.build.build_engine.BuildEngine.build_one", boom)

    worker = BuildModelWorker(Config(), "g.faa", "eco")
    errors, finished = [], []
    worker.signals.error.connect(errors.append)
    worker.signals.finished.connect(lambda: finished.append(True))
    worker.run()
    assert errors and "carve exploded" in errors[0]
    assert finished == [True]


def test_batch_build_worker(monkeypatch) -> None:
    from src.build.build_engine import BuildItemResult
    from src.build.build_manifest import BuildJob
    from src.gui.workers import BatchBuildWorker
    from src.utils.config import Config

    def fake_build_batch(self, jobs, options=None, output_dir=None, on_line=None,
                         on_model_built=None, cancel_token=None):
        results = []
        for i, job in enumerate(jobs):
            item = BuildItemResult(job=job, carve_result=None, built=_fake_built(job.label))
            results.append(item)
            if on_line:
                on_line(f"built {job.label}")
            if on_model_built:
                on_model_built(i, item)
        return results

    monkeypatch.setattr("src.build.build_engine.BuildEngine.build_batch", fake_build_batch)

    jobs = [
        BuildJob(Path("eco.faa"), "eco", label="eco"),
        BuildJob(Path("cgb.faa"), "cgb", label="cgb"),
    ]
    worker = BatchBuildWorker(Config(), jobs)
    built_events, progress, results = [], [], []
    worker.signals.model_built.connect(built_events.append)
    worker.signals.progress.connect(lambda d, t, label: progress.append((d, t, label)))
    worker.signals.result.connect(results.append)
    worker.run()

    assert len(built_events) == 2
    assert progress[-1][0] == 2 and progress[-1][1] == 2
    assert results and len(results[0]) == 2
