"""Tests for CLI model-construction argument parsing and dispatch guards."""

from __future__ import annotations

import argparse

import pytest

from src import cli
from src.utils.config import Config


def _parse(args: list[str]) -> argparse.Namespace:
    return cli._build_parser().parse_args(args)


def test_positional_model_optional() -> None:
    ns = _parse(["--build", "g.faa"])
    assert ns.model is None
    assert ns.build == "g.faa"


def test_build_flags_parse() -> None:
    ns = _parse([
        "--build", "g.faa",
        "--carveme-solver", "scip",
        "--carveme-universe", "grampos",
        "--carveme-gapfill-media", "M9,LB",
        "--carveme-init-medium", "M9",
        "--gzip-model",
        "--build-dna",
        "--refine",
        "--build-output", "out.xml",
    ])
    assert ns.carveme_solver == "scip"
    assert ns.carveme_universe == "grampos"
    assert ns.carveme_gapfill_media == "M9,LB"
    assert ns.carveme_init_medium == "M9"
    assert ns.gzip_model is True
    assert ns.build_dna is True
    assert ns.refine is True
    assert ns.build_output == "out.xml"


def test_batch_build_flag() -> None:
    ns = _parse(["--batch-build", "m.csv"])
    assert ns.batch_build == "m.csv"
    assert ns.build is None


def test_apply_carveme_overrides() -> None:
    cfg = Config()
    ns = _parse([
        "--build", "g.faa",
        "--carveme-solver", "cplex",
        "--carveme-universe", "archaea",
        "--carveme-env", "carveme",
        "--carveme-timeout", "600",
        "--gzip-model",
    ])
    cli._apply_carveme_overrides(cfg, ns)
    assert cfg.carveme_solver == "cplex"
    assert cfg.carveme_universe == "archaea"
    assert cfg.carveme_env == "carveme"
    assert cfg.carveme_timeout == 600
    assert cfg.carveme_gzip_output is True


def test_main_model_and_build_mutually_exclusive(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_build", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["model.xml", "--build", "g.faa"])


def test_main_build_and_batch_mutually_exclusive(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_build", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["--build", "g.faa", "--batch-build", "m.csv"])


def test_main_requires_model_without_build() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_main_check_carveme_dispatch(monkeypatch) -> None:
    called = {}
    monkeypatch.setattr(cli, "_run_check_carveme", lambda cfg: called.setdefault("hit", True))
    cli.main(["--check-carveme"])
    assert called.get("hit") is True


def test_main_build_dispatch(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(cli, "_run_build", lambda args, cfg: seen.setdefault("build", args.build))
    cli.main(["--build", "g.faa", "--organism", "eco"])
    assert seen.get("build") == "g.faa"


def test_config_flags_parse() -> None:
    ns = _parse(["--config", "run.yaml", "--config-validate"])
    assert ns.config == "run.yaml"
    assert ns.config_validate is True


def test_main_config_dispatch(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(cli, "_run_pipeline_config", lambda args, cfg: seen.setdefault("cfg", args.config))
    cli.main(["--config", "run.yaml"])
    assert seen.get("cfg") == "run.yaml"


def test_main_config_mutually_exclusive_with_build(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_pipeline_config", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["--config", "run.yaml", "--build", "g.faa"])


def test_main_config_mutually_exclusive_with_model(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_run_pipeline_config", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["model.xml", "--config", "run.yaml"])


def test_main_config_validate_requires_config() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--config-validate"])
