"""Unit tests for the CarveMe subprocess runner (no real `carve` invoked)."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.build.carveme_runner import (
    BuildSpec,
    CarveMeNotInstalledError,
    CarveMeOptions,
    CarveMeRunError,
    CarveMeRunner,
)


def test_build_argv_contains_expected_flags(tmp_path: Path) -> None:
    runner = CarveMeRunner(executable="carve")
    spec = BuildSpec(
        fasta_path=tmp_path / "genome.faa",
        output_path=tmp_path / "out.xml",
        options=CarveMeOptions(
            solver="gurobi", universe="gramneg", gapfill_media="M9,LB", init_medium="M9"
        ),
    )
    argv = runner.build_argv(spec)
    assert argv[0] == "carve"
    assert str(spec.fasta_path) in argv
    assert "-o" in argv and str(spec.output_path) in argv
    assert "--solver" in argv and "gurobi" in argv
    assert "--universe" in argv and "gramneg" in argv
    assert "--gapfill" in argv and "M9,LB" in argv
    assert "--init" in argv and "M9" in argv
    assert "-v" in argv


def test_build_argv_conda_env_prefix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/opt/conda/bin/conda")
    runner = CarveMeRunner(executable="carve", conda_env="carveme")
    spec = BuildSpec(tmp_path / "g.faa", tmp_path / "o.xml", CarveMeOptions())
    argv = runner.build_argv(spec)
    assert argv[:5] == ["/opt/conda/bin/conda", "run", "--no-capture-output", "-n", "carveme"]
    assert "carve" in argv


def test_gzip_output_suffix() -> None:
    assert CarveMeOptions(gzip_output=True).output_suffix() == ".xml.gz"
    assert CarveMeOptions(gzip_output=False).output_suffix() == ".xml"


def test_check_available_reports_ok(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")

    def fake_run(argv, **kwargs):
        joined = " ".join(argv)
        if "carve" in joined and "--help" in joined:
            return SimpleNamespace(returncode=0, stdout="usage: carve", stderr="")
        if "carveme.__version__" in joined:
            return SimpleNamespace(returncode=0, stdout="1.6.6\n", stderr="")
        if "diamond" in joined:
            return SimpleNamespace(returncode=0, stdout="diamond version 2.2.1", stderr="")
        if "import gurobipy" in joined:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = CarveMeRunner(executable="carve")
    avail = runner.check_available(solver="gurobi")
    assert avail.ok
    assert avail.carve_ok and avail.diamond_ok
    assert avail.solver_ok is True
    assert avail.carve_version == "1.6.6"


def test_check_available_missing_carve(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    runner = CarveMeRunner(executable="carve")
    avail = runner.check_available(solver="gurobi")
    assert not avail.ok
    assert "pip install carveme" in avail.message


def test_build_single_missing_fasta(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")
    runner = CarveMeRunner(executable="carve")
    with pytest.raises(CarveMeRunError, match="FASTA file not found"):
        runner.build_single(tmp_path / "nope.faa", tmp_path / "o.xml", CarveMeOptions())


def test_build_single_not_installed(tmp_path: Path, monkeypatch) -> None:
    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    runner = CarveMeRunner(executable="carve")
    with pytest.raises(CarveMeNotInstalledError):
        runner.build_single(fasta, tmp_path / "o.xml", CarveMeOptions())


def test_build_single_success(tmp_path: Path, monkeypatch) -> None:
    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    out = tmp_path / "o.xml"
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")

    def fake_stream(self, argv, timeout, on_line, cancel_token):
        if on_line:
            on_line("building...")
        out.write_text("<sbml/>")  # simulate carve writing the model
        return 0, "building...", False

    monkeypatch.setattr(CarveMeRunner, "_run_streaming", fake_stream)
    runner = CarveMeRunner(executable="carve")
    lines: list[str] = []
    result = runner.build_single(fasta, out, CarveMeOptions(), on_line=lines.append, kegg_code="eco")
    assert result.succeeded
    assert result.kegg_code == "eco"
    assert lines == ["building..."]


def test_build_single_cancelled_raises(tmp_path: Path, monkeypatch) -> None:
    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")
    monkeypatch.setattr(
        CarveMeRunner, "_run_streaming", lambda *a, **k: (-1, "partial", True)
    )
    runner = CarveMeRunner(executable="carve")
    with pytest.raises(CarveMeRunError, match="cancel"):
        runner.build_single(fasta, tmp_path / "o.xml", CarveMeOptions())


def test_build_single_nonzero_exit_raises(tmp_path: Path, monkeypatch) -> None:
    fasta = tmp_path / "g.faa"
    fasta.write_text(">a\nMKV\n")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")
    monkeypatch.setattr(
        CarveMeRunner, "_run_streaming", lambda *a, **k: (1, "boom: solver error", False)
    )
    runner = CarveMeRunner(executable="carve")
    with pytest.raises(CarveMeRunError, match="exit 1"):
        runner.build_single(fasta, tmp_path / "o.xml", CarveMeOptions())


def test_run_streaming_captures_lines() -> None:
    """Exercise the real reader-thread/queue path with a fast subprocess."""
    runner = CarveMeRunner(executable="carve")
    argv = [sys.executable, "-c", "print('LINE1'); print('LINE2')"]
    lines: list[str] = []
    rc, tail, cancelled = runner._run_streaming(argv, 30, lines.append, None)
    assert rc == 0
    assert not cancelled
    assert "LINE1" in lines and "LINE2" in lines


def test_run_streaming_cancel_terminates() -> None:
    runner = CarveMeRunner(executable="carve")
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    token = threading.Event()
    token.set()  # pre-cancelled -> should terminate on first poll
    rc, tail, cancelled = runner._run_streaming(argv, 30, None, token)
    assert cancelled is True


def test_build_batch_continues_on_failure(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "good.faa"
    good.write_text(">a\nMKV\n")
    bad = tmp_path / "bad.faa"
    bad.write_text(">a\nMKV\n")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")

    def fake_single(self, fasta_path, output_path, options=None, on_line=None,
                    cancel_token=None, kegg_code=None, label=""):
        from src.build.carveme_runner import CarveMeResult
        if Path(fasta_path).name == "bad.faa":
            raise CarveMeRunError("carve failed for bad.faa (exit 1)")
        Path(output_path).write_text("<sbml/>")
        return CarveMeResult(
            fasta_path=Path(fasta_path), output_path=Path(output_path),
            returncode=0, kegg_code=kegg_code, label=label,
        )

    monkeypatch.setattr(CarveMeRunner, "build_single", fake_single)
    runner = CarveMeRunner(executable="carve")
    specs = [
        BuildSpec(good, tmp_path / "good.xml", CarveMeOptions(), kegg_code="eco", label="good"),
        BuildSpec(bad, tmp_path / "bad.xml", CarveMeOptions(), kegg_code="cgb", label="bad"),
    ]
    results = runner.build_batch(specs)
    assert len(results) == 2
    assert results[0].succeeded
    assert not results[1].succeeded and results[1].error


def test_build_batch_continues_on_non_carveme_error(tmp_path: Path, monkeypatch) -> None:
    """A non-CarveMeRunError (missing toolchain / OSError) must not abort the batch."""
    from src.build.carveme_runner import CarveMeNotInstalledError, CarveMeResult

    good = tmp_path / "good.faa"
    good.write_text(">a\nMKV\n")
    bad = tmp_path / "bad.faa"
    bad.write_text(">a\nMKV\n")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/carve")

    def fake_single(self, fasta_path, output_path, options=None, on_line=None,
                    cancel_token=None, kegg_code=None, label=""):
        if Path(fasta_path).name == "bad.faa":
            raise CarveMeNotInstalledError("carve not installed")  # sibling of CarveMeRunError
        Path(output_path).write_text("<sbml/>")
        return CarveMeResult(
            fasta_path=Path(fasta_path), output_path=Path(output_path),
            returncode=0, kegg_code=kegg_code, label=label,
        )

    monkeypatch.setattr(CarveMeRunner, "build_single", fake_single)
    runner = CarveMeRunner(executable="carve")
    specs = [
        BuildSpec(good, tmp_path / "good.xml", CarveMeOptions(), label="good"),
        BuildSpec(bad, tmp_path / "bad.xml", CarveMeOptions(), label="bad"),
    ]
    results = runner.build_batch(specs)
    assert len(results) == 2 and all(r is not None for r in results)
    assert results[0].succeeded
    assert not results[1].succeeded and "not installed" in results[1].error
