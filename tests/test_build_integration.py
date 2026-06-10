"""Opt-in integration tests that run the real CarveMe toolchain.

These build actual models from the bundled proteomes and (optionally) run the
real task-aware gap-fill, so they are slow and require ``carve`` + a solver.
They are excluded from the default run via the ``integration`` marker:

    pytest -m integration            # run them
    pytest -m "not integration"      # default: skip them
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.build.build_engine import BuildEngine
from src.build.build_manifest import BuildJob
from src.utils.config import Config

DATA = Path("data")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("carve") is None, reason="carve not installed"),
    pytest.mark.skipif(
        not (DATA / "eco_protein.faa").exists(), reason="test proteomes missing"
    ),
]


def _engine() -> BuildEngine:
    cfg = Config()
    cfg.carveme_solver = "gurobi"  # licensed on the dev box; switch to scip if needed
    return BuildEngine(cfg)


def test_build_single_eco(tmp_path: Path) -> None:
    built = _engine().build_one(DATA / "eco_protein.faa", "eco", output_path=tmp_path / "eco.xml")
    assert built.sbml_path.exists()
    assert built.model_data.reaction_count > 500
    assert built.model_data.metabolite_count > 500
    assert built.model_data.kegg_organism_code == "eco"


def test_build_single_cgb(tmp_path: Path) -> None:
    built = _engine().build_one(DATA / "cgb_protein.faa", "cgb", output_path=tmp_path / "cgb.xml")
    assert built.sbml_path.exists()
    assert built.model_data.reaction_count > 500
    assert built.model_data.kegg_organism_code == "cgb"
    assert built.model_data.organism == "Corynebacterium glutamicum"


def test_build_batch_both(tmp_path: Path) -> None:
    jobs = [
        BuildJob(DATA / "eco_protein.faa", "eco", label="eco"),
        BuildJob(DATA / "cgb_protein.faa", "cgb", label="cgb"),
    ]
    results = _engine().build_batch(jobs, output_dir=tmp_path)
    assert len(results) == 2
    assert all(r.ok for r in results)
    by_code = {r.built.kegg_code: r.built for r in results}
    assert set(by_code) == {"eco", "cgb"}


@pytest.mark.asyncio
async def test_build_then_refine_eco(tmp_path: Path) -> None:
    universal = DATA / "bigg_universal_model_fixed.json"
    tasks = DATA / "universal_essential_tasks.csv"
    if not (universal.exists() and tasks.exists()):
        pytest.skip("universal model / task file not available")

    engine = _engine()
    built = engine.build_one(DATA / "eco_protein.faa", "eco", output_path=tmp_path / "eco.xml")
    outcome = await engine.refine(
        built,
        universal_path=str(universal),
        tasks_path=str(tasks),
        skip_evaluation=True,  # avoid network-heavy evidence; still exercises gap-fill
    )
    # Pipeline ran end to end and produced before/after task verdicts.
    assert outcome.gf_result.total_tasks > 0
    assert outcome.gf_result.task_results_after
