"""Regression coverage for task-local objectives and candidate bounds."""

from __future__ import annotations

import cobra
import pytest

from src.core.cobra_utils import convert_cobra_reaction
from src.core.models import CandidateReaction, EvidenceTier, MetabolicTask, ReactionEvidence
from src.core.task_parser import TaskRunner
from src.gapfill.engine import GapFillEngine
from src.utils.config import Config


def _reaction(
    reaction_id: str,
    stoichiometry: dict[cobra.Metabolite, float],
    bounds: tuple[float, float] = (0.0, 1000.0),
) -> cobra.Reaction:
    reaction = cobra.Reaction(reaction_id)
    reaction.add_metabolites(stoichiometry)
    reaction.bounds = bounds
    return reaction


@pytest.fixture
def draft() -> cobra.Model:
    model = cobra.Model("draft")
    model.solver = "glpk"
    a = cobra.Metabolite("a_c", compartment="c")
    b = cobra.Metabolite("b_c", compartment="c")
    model.add_reactions(
        [_reaction("SOURCE_A", {a: 1.0}, (0.0, 10.0)), _reaction("DRAIN_B", {b: -1.0})]
    )
    return model


def _universal(draft: cobra.Model, reaction_ids: list[str]) -> cobra.Model:
    universal = cobra.Model("universal")
    universal.solver = "glpk"
    universal.add_reactions(
        [
            _reaction(
                reaction_id,
                {draft.metabolites.a_c.copy(): -1.0, draft.metabolites.b_c.copy(): 1.0},
            )
            for reaction_id in reaction_ids
        ]
    )
    return universal


@pytest.mark.parametrize("task_type,target_id", [("Metabolite", "b_c"), ("Reaction", "TARGET")])
def test_tasks_maximize_independently_of_draft_objective(
    draft: cobra.Model, task_type: str, target_id: str
) -> None:
    draft.add_reactions([_universal(draft, ["TARGET"]).reactions.TARGET.copy()])
    draft.objective = "TARGET"
    draft.objective_direction = "min"
    runner = TaskRunner()
    positive = MetabolicTask(
        task_id="POSITIVE",
        task_type=task_type,
        target_id=target_id,
        expected_operator=">",
        expected_value=0.0,
    )
    negative = MetabolicTask(
        task_id="NEGATIVE",
        task_type=task_type,
        target_id=target_id,
        expected_operator="=",
        expected_value=0.0,
    )

    positive_result = runner.run_task(draft, positive)
    negative_result = runner.run_task(draft, negative)

    assert positive_result.passed
    assert positive_result.actual_value == pytest.approx(10.0)
    assert not negative_result.passed
    assert negative_result.actual_value == pytest.approx(10.0)
    assert draft.objective_direction == "min"


@pytest.mark.parametrize("forbidden_id", ["FORBIDDEN", "FORBIDDENpp"])
async def test_missing_candidate_obeys_task_constraint(
    draft: cobra.Model, forbidden_id: str
) -> None:
    universal = _universal(draft, [forbidden_id, "GOOD"])
    task = MetabolicTask(
        task_id="CONSTRAINED",
        task_type="Metabolite",
        target_id="b_c",
        constraints={"FORBIDDEN": (0.0, 0.0)},
        expected_operator=">",
        expected_value=0.0,
    )
    candidates = [
        CandidateReaction(reaction=convert_cobra_reaction(reaction), organism_exists=True)
        for reaction in universal.reactions
    ]
    evidence = {
        forbidden_id: ReactionEvidence(
            reaction_id=forbidden_id,
            evidence_tier=EvidenceTier.HIGH,
            verified_kegg_reaction_ids=["R00001"],
        ),
        "GOOD": ReactionEvidence(reaction_id="GOOD", evidence_tier=EvidenceTier.LOW),
    }
    engine = GapFillEngine(Config())

    result = await engine.run(draft, universal, candidates, [task], evidence)

    assert result.tasks_fixed == 1
    assert [candidate.reaction.id for candidate in result.added_reactions] == ["GOOD"]
    assert result.task_results_after[0].actual_value == pytest.approx(10.0)
    assert universal.reactions.get_by_id(forbidden_id).bounds == (0.0, 1000.0)
    assert forbidden_id not in draft.reactions


def test_retry_validation_applies_constraints_after_adding_candidates(draft: cobra.Model) -> None:
    universal = _universal(draft, ["FORBIDDEN"])
    task = MetabolicTask(
        task_id="CONSTRAINED",
        task_type="Metabolite",
        target_id="b_c",
        constraints={"FORBIDDEN": (0.0, 0.0)},
        expected_operator=">",
        expected_value=0.0,
    )

    assert not GapFillEngine(Config())._reactions_satisfy_task(
        draft, universal, task, [universal.reactions.FORBIDDEN]
    )


async def test_draft_exact_constraint_does_not_block_suffixed_candidate(draft: cobra.Model) -> None:
    draft.add_reactions([_universal(draft, ["FORBIDDEN"]).reactions.FORBIDDEN.copy()])
    universal = _universal(draft, ["FORBIDDENpp"])
    candidate = CandidateReaction(reaction=convert_cobra_reaction(universal.reactions.FORBIDDENpp))
    task = MetabolicTask(
        task_id="EXACT_CONSTRAINT",
        task_type="Metabolite",
        target_id="b_c",
        constraints={"FORBIDDEN": (0.0, 0.0)},
        expected_operator=">",
        expected_value=0.0,
    )

    result = await GapFillEngine(Config()).run(draft, universal, [candidate], [task], {})

    assert result.tasks_fixed == 1
    assert [added.reaction.id for added in result.added_reactions] == ["FORBIDDENpp"]
    assert result.task_results_after[0].actual_value == pytest.approx(10.0)
    assert universal.reactions.FORBIDDENpp.bounds == (0.0, 1000.0)
    assert draft.reactions.FORBIDDEN.bounds == (0.0, 1000.0)


async def test_positive_candidate_bounds_are_task_local(draft: cobra.Model) -> None:
    universal = _universal(draft, ["TARGET"])
    universal.reactions.TARGET.bounds = (0.0, 0.0)
    candidate = CandidateReaction(reaction=convert_cobra_reaction(universal.reactions.TARGET))
    task = MetabolicTask(
        task_id="POSITIVE_BOUND",
        task_type="Metabolite",
        target_id="b_c",
        constraints={"TARGET": (1.0, 5.0)},
        expected_operator=">=",
        expected_value=2.0,
    )

    result = await GapFillEngine(Config()).run(draft, universal, [candidate], [task], {})

    assert result.tasks_fixed == 1
    assert result.task_results_after[0].actual_value == pytest.approx(5.0)
    assert draft.reactions.TARGET.bounds == (0.0, 0.0)
    assert universal.reactions.TARGET.bounds == (0.0, 0.0)


async def test_preseeded_target_keeps_original_bounds_in_final_model(draft: cobra.Model) -> None:
    universal = _universal(draft, ["TARGET"])
    candidate = CandidateReaction(reaction=convert_cobra_reaction(universal.reactions.TARGET))
    tasks = [
        MetabolicTask(
            task_id="TARGET_TASK",
            task_type="Reaction",
            target_id="TARGET",
            constraints={"TARGET": (0.0, 1.0)},
            expected_operator=">",
            expected_value=0.0,
        ),
        MetabolicTask(
            task_id="PRODUCTION_TASK",
            task_type="Metabolite",
            target_id="b_c",
            expected_operator=">=",
            expected_value=2.0,
        ),
    ]

    result = await GapFillEngine(Config()).run(draft, universal, [candidate], tasks, {})

    assert result.tasks_fixed == 2
    assert all(task_result.passed for task_result in result.task_results_after)
    assert [r.actual_value for r in result.task_results_after] == pytest.approx([1.0, 10.0])
    assert draft.reactions.TARGET.bounds == (0.0, 1000.0)
    assert universal.reactions.TARGET.bounds == (0.0, 1000.0)
    assert draft.reactions.TARGET is not universal.reactions.TARGET
