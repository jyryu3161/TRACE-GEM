"""Unweighted selection must ignore evidence and organism preferences."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import cobra
import pytest

from src.cli import async_gapfill_main
from src.core.cobra_utils import convert_cobra_reaction, sync_model_data_from_cobra
from src.core.models import (
    CandidateReaction,
    EvidenceTier,
    GapFillResult,
    MetabolicTask,
    ModelData,
    ReactionEvidence,
)
from src.core.task_parser import TaskRunner
from src.gapfill.engine import GapFillEngine
from src.gapfill.refine import refine_model_data
from src.utils.config import Config


@pytest.fixture
def alternative_routes():
    model = cobra.Model("draft")
    model.solver = "glpk"
    a, b, target = [cobra.Metabolite(mid, compartment="c") for mid in ("a_c", "b_c", "t_c")]
    source = cobra.Reaction("SOURCE_A", lower_bound=0, upper_bound=10)
    source.add_metabolites({a: 1})
    demand = cobra.Reaction("DM_t_c")
    demand.add_metabolites({target: -1})
    model.add_reactions([source, demand])
    model.objective = demand

    universal = cobra.Model("universal")
    universal.solver = "glpk"
    for rid, stoichiometry in (
        ("SHORT", {a: -1, target: 1}),
        ("FIRST", {a: -1, b: 1}),
        ("SECOND", {b: -1, target: 1}),
    ):
        reaction = cobra.Reaction(rid)
        reaction.add_metabolites(stoichiometry)
        universal.add_reactions([reaction])
    candidates = [
        CandidateReaction(
            reaction=convert_cobra_reaction(reaction),
            organism_exists=reaction.id != "SHORT",
            evidence_tier=EvidenceTier.HIGH,
        )
        for reaction in universal.reactions
    ]
    evidence = {
        candidate.reaction.id: ReactionEvidence(
            reaction_id=candidate.reaction.id,
            evidence_tier=EvidenceTier.LOW
            if candidate.reaction.id == "SHORT"
            else EvidenceTier.HIGH,
            verified_kegg_reaction_ids=["R00001"],
        )
        for candidate in candidates
    }
    task = MetabolicTask("T", "Metabolite", "t_c", expected_operator=">=", expected_value=1)
    return model, universal, candidates, evidence, task


@pytest.mark.parametrize("weighted", [True, False])
async def test_selection_uses_explicit_weighting_mode(alternative_routes, weighted):
    model, universal, candidates, evidence, task = alternative_routes
    engine = GapFillEngine(Config(gapfill_iterations=1), evidence_weighted=weighted)
    result = await engine.run(model, universal, candidates, [task], evidence)

    expected = {"FIRST", "SECOND"} if weighted else {"SHORT"}
    assert {candidate.reaction.id for candidate in result.added_reactions} == expected
    assert result.tasks_fixed == 1
    if not weighted:
        assert all(candidate.penalty == 1.0 for candidate in candidates)
        assert all(candidate.evidence_tier is None for candidate in candidates)


async def test_unweighted_resume_keeps_uniform_penalties(alternative_routes):
    model, universal, candidates, evidence, task = alternative_routes
    checkpoint = GapFillResult(
        task_results_before=TaskRunner().run_all(model, [task]), completed_phase=2
    )
    engine = GapFillEngine(Config(gapfill_iterations=1), evidence_weighted=False)
    result = await engine.run(
        model,
        universal,
        candidates,
        [task],
        evidence,
        start_phase=3,
        preloaded_result=checkpoint,
    )
    assert [candidate.reaction.id for candidate in result.added_reactions] == ["SHORT"]
    assert all(candidate.penalty == 1.0 for candidate in candidates)


async def test_unweighted_initialization_skips_organism_lookup(monkeypatch):
    organism_filter = MagicMock()
    monkeypatch.setattr("src.gapfill.engine.OrganismFilter", organism_filter)
    engine = GapFillEngine(Config(), evidence_weighted=False)
    try:
        await engine.initialize("eco")
        organism_filter.assert_not_called()
    finally:
        await engine.close()


@pytest.mark.parametrize("entrypoint", ["cli", "refine"])
@pytest.mark.parametrize("skip_evaluation", [True, False])
async def test_entrypoints_select_and_report_the_requested_mode(
    alternative_routes, tmp_path, monkeypatch, entrypoint, skip_evaluation
):
    model, universal, _candidates, evidence, _task = alternative_routes
    model_data = sync_model_data_from_cobra(ModelData(id="draft", name="draft"), model)
    universal_path = str(tmp_path / "universal.json")
    cobra.io.save_json_model(universal, universal_path)
    tasks_path = str(tmp_path / "tasks.csv")
    (tmp_path / "tasks.csv").write_text(
        "Task ID,Type,ID,Medium,Constraints,Expected value,Description,Category\n"
        "T,Metabolite,t_c,,,>=1,Produce target,Test\n"
    )

    evidence_engine = MagicMock()
    evidence_engine.initialize = AsyncMock()
    evidence_engine.close = AsyncMock()
    evidence_engine.cache_manager = None
    evidence_engine.mapping_data = None
    evidence_engine.evaluate_candidates_batch = AsyncMock(return_value=evidence)
    monkeypatch.setattr("src.evidence.engine.EvidenceEngine", lambda config: evidence_engine)
    initialize_organism = AsyncMock()
    monkeypatch.setattr(
        "src.gapfill.organism_filter.OrganismFilter.initialize", initialize_organism
    )

    async def filter_candidates(self, candidates, **kwargs):
        for candidate in candidates:
            candidate.organism_exists = candidate.reaction.id != "SHORT"
        return candidates

    monkeypatch.setattr(
        "src.gapfill.organism_filter.OrganismFilter.filter_candidates", filter_candidates
    )
    monkeypatch.setattr("src.gapfill.gpr_assigner.GPRAssigner.assign_batch", AsyncMock())

    if entrypoint == "cli":
        manifest_path = str(tmp_path / "run.manifest.json")
        await async_gapfill_main(
            Config(gapfill_iterations=1),
            model_data,
            universal_path,
            tasks_path,
            medium_arg=None,
            output_model=None,
            output_report=None,
            skip_evaluation=skip_evaluation,
            output_manifest=manifest_path,
        )
        manifest = json.loads((tmp_path / "run.manifest.json").read_text())
        if skip_evaluation:
            assert manifest["penalty_policy"] == {"mode": "unweighted", "candidate_penalty": 1.0}
        else:
            assert manifest["penalty_policy"]["mode"] == "evidence_weighted"
    else:
        await refine_model_data(
            Config(gapfill_iterations=1),
            model_data,
            universal_path=universal_path,
            tasks_path=tasks_path,
            skip_evaluation=skip_evaluation,
        )

    expected = {"SHORT"} if skip_evaluation else {"FIRST", "SECOND"}
    assert {reaction.id for reaction in model.reactions} - {"SOURCE_A", "DM_t_c"} == expected
    if skip_evaluation:
        evidence_engine.evaluate_candidates_batch.assert_not_awaited()
        initialize_organism.assert_not_awaited()
    else:
        evidence_engine.evaluate_candidates_batch.assert_awaited_once()
        initialize_organism.assert_awaited_once()
