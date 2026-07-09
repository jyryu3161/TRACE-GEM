"""Tests for the YAML pipeline (parse, validate, execute with mocked engines)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline import (
    CarveMeDefaults,
    PipelineError,
    _fmt,
    apply_carveme_defaults,
    load_pipeline,
    run_pipeline,
)
from src.utils.config import Config


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text)
    return p


def test_load_build_pipeline(tmp_path: Path) -> None:
    fa = _write(tmp_path, "eco.faa", ">a\nM\n")
    universal = _write(tmp_path, "u.json", "{}")
    tasks = _write(tmp_path, "t.csv", "x")
    cfg = _write(
        tmp_path, "p.yaml",
        f"carveme: {{solver: scip, universe: gramneg}}\n"
        f"build:\n  mode: single\n  jobs:\n    - {{fasta: {fa}, kegg_code: eco}}\n"
        f"refine:\n  enabled: true\n  universal: {universal}\n  tasks: {tasks}\n",
    )
    spec = load_pipeline(cfg)
    assert spec.carveme.solver == "scip"
    assert spec.build.mode == "single"
    assert spec.build.jobs[0]["kegg_code"] == "eco"
    assert spec.refine.enabled and spec.models == []


def test_load_models_pipeline(tmp_path: Path) -> None:
    m = _write(tmp_path, "iML.xml", "<x/>")
    cfg = _write(
        tmp_path, "p.yaml",
        f"models:\n  - {{path: {m}, kegg_code: eco, label: ecoli}}\n"
        f"refine:\n  enabled: false\n",
    )
    spec = load_pipeline(cfg)
    assert spec.build is None
    assert len(spec.models) == 1 and spec.models[0].kegg_code == "eco"


def test_validate_requires_exactly_one_input(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "p.yaml", "refine: {enabled: false}\n")
    with pytest.raises(PipelineError, match="exactly one of 'build' or 'models'"):
        load_pipeline(cfg)


def test_validate_single_requires_one_job(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.faa", ">a\nM\n")
    b = _write(tmp_path, "b.faa", ">a\nM\n")
    cfg = _write(
        tmp_path, "p.yaml",
        f"build:\n  mode: single\n  jobs:\n"
        f"    - {{fasta: {a}, kegg_code: eco}}\n    - {{fasta: {b}, kegg_code: cgb}}\n",
    )
    with pytest.raises(PipelineError, match="single requires exactly one job"):
        load_pipeline(cfg)


def test_validate_missing_kegg_and_fasta(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path, "p.yaml",
        "build:\n  mode: batch\n  jobs:\n"
        "    - {fasta: nope.faa, kegg_code: eco}\n"
        "    - {fasta: , kegg_code: }\n",
    )
    with pytest.raises(PipelineError) as exc:
        load_pipeline(cfg)
    msg = str(exc.value)
    assert "fasta not found: nope.faa" in msg
    assert "missing 'kegg_code'" in msg


def test_validate_refine_inputs(tmp_path: Path) -> None:
    fa = _write(tmp_path, "eco.faa", ">a\nM\n")
    cfg = _write(
        tmp_path, "p.yaml",
        f"build:\n  mode: single\n  jobs:\n    - {{fasta: {fa}, kegg_code: eco}}\n"
        f"refine:\n  enabled: true\n  universal: missing_u.json\n  tasks: missing_t.csv\n",
    )
    with pytest.raises(PipelineError) as exc:
        load_pipeline(cfg)
    assert "refine.universal not found" in str(exc.value)
    assert "refine.tasks not found" in str(exc.value)


def test_validate_bad_solver(tmp_path: Path) -> None:
    m = _write(tmp_path, "m.xml", "<x/>")
    cfg = _write(
        tmp_path, "p.yaml",
        f"carveme: {{solver: glpk}}\nmodels:\n  - {{path: {m}, kegg_code: eco}}\n",
    )
    with pytest.raises(PipelineError, match="carveme.solver must be one of"):
        load_pipeline(cfg)


def test_validate_non_dict_section(tmp_path: Path) -> None:
    m = _write(tmp_path, "m.xml", "<x/>")
    cfg = _write(
        tmp_path, "p.yaml",
        f"models:\n  - {{path: {m}, kegg_code: eco}}\nrefine: enabled\n",
    )
    with pytest.raises(PipelineError, match="'refine' must be a mapping"):
        load_pipeline(cfg)


def test_validate_bad_timeout_type(tmp_path: Path) -> None:
    m = _write(tmp_path, "m.xml", "<x/>")
    cfg = _write(
        tmp_path, "p.yaml",
        f"carveme: {{timeout: soon}}\nmodels:\n  - {{path: {m}, kegg_code: eco}}\n",
    )
    with pytest.raises(PipelineError, match="carveme.timeout must be an integer"):
        load_pipeline(cfg)


def test_output_collision_detected(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    from src.core.models import ModelData, Reaction
    from src.pipeline import run_pipeline
    from src.utils.config import Config

    monkeypatch.setattr(
        "src.core.sbml_parser.SBMLParser.load_model",
        lambda self, p: ModelData(
            id=Path(p).stem, name="m",
            reactions=[Reaction(id="R1", name="r", equation="a -> b")],
            metabolites=[], genes=[],
        ),
    )
    m1 = _write(tmp_path, "m1.xml", "<x/>")
    m2 = _write(tmp_path, "m2.xml", "<x/>")
    universal = _write(tmp_path, "u.json", "{}")
    tasks = _write(tmp_path, "t.csv", "x")
    cfg = _write(
        tmp_path, "p.yaml",
        f"models:\n  - {{path: {m1}, kegg_code: eco, label: same}}\n"
        f"  - {{path: {m2}, kegg_code: cgb, label: same}}\n"
        f"refine:\n  enabled: true\n  universal: {universal}\n  tasks: {tasks}\n"
        f"  output_model: out/fixed.xml\n",  # fixed (non-{label}) -> collides
    )
    spec = load_pipeline(cfg)
    with pytest.raises(PipelineError, match="Output path collision"):
        asyncio.run(run_pipeline(spec, Config(), log=lambda _m: None))


def test_apply_carveme_defaults() -> None:
    cfg = Config()
    apply_carveme_defaults(cfg, CarveMeDefaults(solver="scip", universe="grampos", max_parallel=4))
    assert cfg.carveme_solver == "scip"
    assert cfg.carveme_universe == "grampos"
    assert cfg.carveme_max_parallel == 4


def test_cli_flags_win_over_yaml_carveme_defaults() -> None:
    """Regression: an explicit CLI flag must take precedence over the YAML
    carveme block (CLI > YAML > defaults), not be overwritten by it."""
    cfg = Config()
    cfg.carveme_solver = "scip"  # as if set by --carveme-solver scip
    cfg.carveme_universe = "grampos"

    apply_carveme_defaults(
        cfg,
        CarveMeDefaults(solver="gurobi", universe="gramneg", max_parallel=4),
        cli_overridden={"carveme_solver"},
    )

    assert cfg.carveme_solver == "scip"  # CLI flag preserved
    assert cfg.carveme_universe == "gramneg"  # not CLI-set → YAML applies
    assert cfg.carveme_max_parallel == 4  # not CLI-set → YAML applies


def test_fmt_templating() -> None:
    assert _fmt("out/{label}_{model}.xml", "ecoli", "iML1515") == "out/ecoli_iML1515.xml"


@pytest.mark.asyncio
async def test_run_pipeline_models_refine(tmp_path: Path, monkeypatch) -> None:
    import src.cli as cli_mod
    from src.core.models import ModelData, Reaction

    def fake_load(self, path):
        md = ModelData(
            id=Path(path).stem, name="m",
            reactions=[Reaction(id="R1", name="r1", equation="a -> b")],
            metabolites=[], genes=[],
        )
        md.cobra_model = object()
        return md

    monkeypatch.setattr("src.core.sbml_parser.SBMLParser.load_model", fake_load)

    calls: dict[str, list] = {"refine": []}

    async def fake_gapfill(**kwargs):
        calls["refine"].append(kwargs)

    monkeypatch.setattr(cli_mod, "async_gapfill_main", fake_gapfill)

    m = _write(tmp_path, "a.xml", "<x/>")
    universal = _write(tmp_path, "u.json", "{}")
    tasks = _write(tmp_path, "t.csv", "x")
    cfg_yaml = _write(
        tmp_path, "p.yaml",
        f"models:\n  - {{path: {m}, kegg_code: eco, label: ecoli}}\n"
        f"refine:\n  enabled: true\n  universal: {universal}\n  tasks: {tasks}\n"
        f"  output_model: {tmp_path}/out/{{label}}_refined.xml\n",
    )
    spec = load_pipeline(cfg_yaml)
    config = Config()
    result = await run_pipeline(spec, config, log=lambda _m: None)

    assert result.models_built == 1
    assert result.models_refined == 1
    assert len(calls["refine"]) == 1
    # organism (taxonomy) propagated to config + templated output resolved
    assert config.kegg_organism_code == "eco"
    assert calls["refine"][0]["output_model"].endswith("/out/ecoli_refined.xml")
