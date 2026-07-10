"""Unit tests for BuildEngine (CarveMe runner + SBMLParser are mocked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.build.build_engine import BuildEngine, BuildItemResult
from src.build.build_manifest import BuildJob
from src.build.carveme_runner import CarveMeResult
from src.core.models import GapFillResult, ModelData
from src.utils.config import Config


class _FakeRunner:
    """Stand-in CarveMeRunner that "writes" SBML and never calls carve."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []

    def build_single(
        self,
        fasta_path,
        output_path,
        options=None,
        on_line=None,
        cancel_token=None,
        kegg_code=None,
        label="",
    ):
        self.calls.append(Path(fasta_path).name)
        if on_line:
            on_line(f"building {Path(fasta_path).name}")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("<sbml/>")
        return CarveMeResult(
            fasta_path=Path(fasta_path),
            output_path=Path(output_path),
            returncode=0,
            kegg_code=kegg_code,
            label=label or Path(fasta_path).stem,
        )

    def build_batch(
        self,
        specs,
        on_line=None,
        on_item_start=None,
        on_item_done=None,
        cancel_token=None,
        max_parallel=1,
    ):
        results = []
        for index, spec in enumerate(specs):
            if Path(spec.fasta_path).name in self.fail:
                res = CarveMeResult(
                    fasta_path=spec.fasta_path,
                    output_path=spec.output_path,
                    error="boom",
                    kegg_code=spec.kegg_code,
                    label=spec.label,
                )
            else:
                res = self.build_single(
                    spec.fasta_path,
                    spec.output_path,
                    spec.options,
                    kegg_code=spec.kegg_code,
                    label=spec.label,
                )
            results.append(res)
            if on_item_done:
                on_item_done(index, res)
        return results


def _fake_model(model_id: str = "eco_built") -> ModelData:
    return ModelData(id=model_id, name=model_id, reactions=[], metabolites=[], genes=[])


@pytest.fixture
def patched_loader(monkeypatch):
    def fake_load_model(self, path):
        return _fake_model(Path(path).stem)

    monkeypatch.setattr("src.core.sbml_parser.SBMLParser.load_model", fake_load_model)


def test_rename_solver_reserved_reactions() -> None:
    import cobra

    from src.core.cobra_utils import is_solver_reserved_id, rename_solver_reserved_reactions

    m = cobra.Model("t")
    a = cobra.Metabolite("a_c")
    b = cobra.Metabolite("b_c")
    reserved = cobra.Reaction("St")  # lowercases to LP keyword "st"
    reserved.add_metabolites({a: -1, b: 1})
    ok = cobra.Reaction("PFK")
    ok.add_metabolites({a: -1, b: 1})
    m.add_reactions([reserved, ok])

    renames = rename_solver_reserved_reactions(m)
    assert renames == [("St", "St_rxn")]
    ids = m.reactions.list_attr("id")
    assert "St" not in ids and "St_rxn" in ids and "PFK" in ids
    assert is_solver_reserved_id("St") and not is_solver_reserved_id("PFK")
    # idempotent: second pass renames nothing
    assert rename_solver_reserved_reactions(m) == []


def test_options_from_config_defaults() -> None:
    cfg = Config()
    cfg.carveme_solver = "gurobi"
    cfg.carveme_universe = "gramneg"
    engine = BuildEngine(cfg, runner=_FakeRunner())
    opts = engine.options_from_config()
    assert opts.solver == "gurobi"
    assert opts.universe == "gramneg"
    # Explicit override wins
    opts2 = engine.options_from_config(solver="scip", universe="")
    assert opts2.solver == "scip" and opts2.universe == ""


def test_options_from_config_universe_file() -> None:
    cfg = Config()
    cfg.carveme_universe = "bacteria"
    cfg.carveme_universe_file = "/u/custom.xml.gz"
    engine = BuildEngine(cfg, runner=_FakeRunner())
    # config-backed
    assert engine.options_from_config().universe_file == "/u/custom.xml.gz"
    # explicit override
    assert engine.options_from_config(universe_file="/other.xml").universe_file == "/other.xml"


def test_spec_for_job_per_job_universe_file() -> None:
    cfg = Config()
    cfg.carveme_universe_file = "/global.xml.gz"
    engine = BuildEngine(cfg, runner=_FakeRunner())
    base = engine.options_from_config()
    # per-job universe_file overrides the global one
    job = BuildJob(Path("g.faa"), "eco", universe_file="/job_specific.xml.gz")
    spec = engine._spec_for_job(job, Path("out"), base)
    assert spec.options.universe_file == "/job_specific.xml.gz"
    # falls back to global when the job has none
    job2 = BuildJob(Path("g2.faa"), "cgb")
    spec2 = engine._spec_for_job(job2, Path("out"), base)
    assert spec2.options.universe_file == "/global.xml.gz"


def test_spec_for_job_per_job_universe_overrides_global_universe_file() -> None:
    """Per-job named universe must beat a global universe_file (cross-dimension)."""
    from src.build.carveme_runner import CarveMeRunner

    cfg = Config()
    cfg.carveme_universe_file = "/global.xml.gz"
    engine = BuildEngine(cfg, runner=_FakeRunner())
    base = engine.options_from_config()

    # A row selecting a named universe must clear the inherited global universe_file,
    # otherwise build_argv would silently drop --universe in favor of the global file.
    job = BuildJob(Path("g.faa"), "eco", universe="gramneg")
    spec = engine._spec_for_job(job, Path("out"), base)
    assert spec.options.universe == "gramneg"
    assert spec.options.universe_file == ""
    argv = CarveMeRunner(executable="carve").build_argv(spec)
    assert "--universe" in argv and "gramneg" in argv
    assert "--universe-file" not in argv

    # Reverse: a per-job universe_file clears any inherited/global named universe.
    cfg2 = Config()
    cfg2.carveme_universe = "bacteria"
    engine2 = BuildEngine(cfg2, runner=_FakeRunner())
    base2 = engine2.options_from_config()
    job2 = BuildJob(Path("g.faa"), "eco", universe_file="/job.xml.gz")
    spec2 = engine2._spec_for_job(job2, Path("out"), base2)
    assert spec2.options.universe_file == "/job.xml.gz"
    assert spec2.options.universe == ""


def test_build_one_attaches_organism(tmp_path: Path, patched_loader) -> None:
    cfg = Config()
    engine = BuildEngine(cfg, runner=_FakeRunner())
    built = engine.build_one(tmp_path / "eco.faa", "eco", output_path=tmp_path / "eco.xml")
    assert built.model_data.kegg_organism_code == "eco"
    assert built.model_data.organism == "Escherichia coli"
    assert built.sbml_path == tmp_path / "eco.xml"
    assert built.kegg_code == "eco"


def test_build_batch_mixed_success(tmp_path: Path, patched_loader) -> None:
    cfg = Config()
    runner = _FakeRunner(fail={"cgb.faa"})
    engine = BuildEngine(cfg, runner=runner)
    (tmp_path / "eco.faa").write_text(">a\nM\n")
    (tmp_path / "cgb.faa").write_text(">a\nM\n")
    jobs = [
        BuildJob(tmp_path / "eco.faa", "eco", label="eco"),
        BuildJob(tmp_path / "cgb.faa", "cgb", label="cgb"),
    ]
    built_events: list[BuildItemResult] = []
    results = engine.build_batch(
        jobs, output_dir=tmp_path / "out", on_model_built=lambda i, it: built_events.append(it)
    )
    assert len(results) == 2
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    assert len(ok) == 1 and ok[0].built.model_data.kegg_organism_code == "eco"
    assert len(bad) == 1 and bad[0].job.kegg_code == "cgb"
    assert len(built_events) == 2


def test_build_batch_unique_output_paths(tmp_path: Path, patched_loader) -> None:
    """Same-stem FASTAs in different dirs must not overwrite each other."""
    cfg = Config()
    engine = BuildEngine(cfg, runner=_FakeRunner())
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "genome.faa").write_text(">x\nM\n")
    (tmp_path / "b" / "genome.faa").write_text(">x\nM\n")
    jobs = [
        BuildJob(tmp_path / "a" / "genome.faa", "eco", label="A"),
        BuildJob(tmp_path / "b" / "genome.faa", "cgb", label="B"),
    ]
    results = engine.build_batch(jobs, output_dir=tmp_path / "out")
    ok = [r for r in results if r.ok]
    assert len(ok) == 2
    paths = {str(r.built.sbml_path) for r in ok}
    assert len(paths) == 2, f"output paths collided: {paths}"


@pytest.mark.asyncio
async def test_refine_delegates_to_core(tmp_path: Path, monkeypatch) -> None:
    from src.build import build_engine as be_mod

    captured = {}

    async def fake_refine(config, model_data, **kwargs):
        captured["model"] = model_data
        captured["kwargs"] = kwargs
        from src.gapfill.refine import RefineOutcome

        return RefineOutcome(gf_result=GapFillResult(total_tasks=3, tasks_fixed=1))

    monkeypatch.setattr(be_mod, "refine_model_data", fake_refine)

    cfg = Config()
    engine = BuildEngine(cfg, runner=_FakeRunner())
    md = _fake_model()
    md.kegg_organism_code = "cgb"
    md.cobra_model = object()
    from src.build.build_engine import BuiltModel

    built = BuiltModel(
        model_data=md,
        sbml_path=tmp_path / "cgb.xml",
        kegg_code="cgb",
        carve_result=CarveMeResult(fasta_path=tmp_path / "c.faa", output_path=tmp_path / "cgb.xml"),
    )
    outcome = await engine.refine(built, universal_path="u.json", tasks_path="t.csv")
    assert outcome.gf_result.tasks_fixed == 1
    assert captured["model"] is md
    # organism propagated to config for organism filtering
    assert cfg.kegg_organism_code == "cgb"
    assert cfg.organism_name == "Corynebacterium glutamicum"
