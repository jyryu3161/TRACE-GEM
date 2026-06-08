"""Tests for GapFillEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import cobra
import pytest

from src.core.models import (
    CandidateReaction,
    GapFillResult,
    MetabolicTask,
    Reaction,
    ReactionEvidence,
    TaskResult,
)
from src.gapfill.engine import GapFillEngine
from src.utils.config import Config


@pytest.fixture
def config() -> Config:
    return Config(
        gapfill_lower_bound=0.05,
        gapfill_penalty_epsilon=0.01,
        gapfill_organism_penalty_multiplier=10.0,
        gapfill_no_kegg_penalty_multiplier=2.0,
    )


@pytest.fixture
def engine(config: Config) -> GapFillEngine:
    return GapFillEngine(config)


@pytest.fixture
def sample_tasks() -> list[MetabolicTask]:
    return [
        MetabolicTask(
            task_id="T001",
            task_type="Reaction",
            target_id="PFK",
            expected_operator=">",
            expected_value=0.0,
            description="PFK flux",
            category="Glycolysis",
        ),
        MetabolicTask(
            task_id="T002",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">",
            expected_value=0.0,
            description="ATP production",
            category="Energy",
        ),
    ]


@pytest.fixture
def sample_candidates() -> list[CandidateReaction]:
    return [
        CandidateReaction(
            reaction=Reaction(
                id="GLNS",
                name="Glutamine synthetase",
                equation="glu + atp + nh4 -> gln + adp + pi",
                annotation={"KEGG Reaction": ["R00253"]},
            ),
        ),
        CandidateReaction(
            reaction=Reaction(
                id="TKT1",
                name="Transketolase",
                equation="r5p + xu5p -> g3p + s7p",
            ),
        ),
    ]


@pytest.fixture
def sample_evidence() -> dict[str, ReactionEvidence]:
    ev = ReactionEvidence(reaction_id="GLNS")
    ev.confidence_score = 0.85
    ev.kegg_reaction_ids = ["R00253"]
    return {"GLNS": ev}


class TestGapFillEngine:
    @pytest.mark.asyncio
    async def test_run_all_tasks_pass(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """If all tasks pass initially, no gap-filling occurs."""
        mock_model = MagicMock()
        mock_universal = MagicMock()

        # All tasks pass
        passing_results = [
            TaskResult(task=t, passed=True, actual_value=1.0) for t in sample_tasks
        ]

        with patch.object(
            engine._task_runner, "run_all", return_value=passing_results
        ):
            result = await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        assert result.total_tasks == 2
        assert len(result.added_reactions) == 0
        assert result.tasks_fixed == 0
        # task_results_after should be same as before when all pass
        assert len(result.task_results_after) == 2

    @pytest.mark.asyncio
    async def test_run_with_failed_tasks(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """Failed tasks trigger gap-filling."""
        mock_model = MagicMock()
        mock_universal = MagicMock()

        # First task fails, second passes
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        # After gap-fill, all pass
        after_results = [
            TaskResult(task=sample_tasks[0], passed=True, actual_value=0.5),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]

        call_count = [0]

        def mock_run_all(model, tasks, progress_callback=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return before_results
            return after_results

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_run_gapfill", new_callable=AsyncMock, return_value=[]):
            result = await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        assert result.total_tasks == 2
        assert result.tasks_fixed == 1  # T001 went from fail to pass

    @pytest.mark.asyncio
    async def test_infeasible_task_recorded(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """Infeasible tasks are recorded in the result."""
        mock_model = MagicMock()
        mock_universal = MagicMock()

        # Task fails
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        after_results = list(before_results)

        call_count = [0]

        def mock_run_all(model, tasks, progress_callback=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return before_results
            return after_results

        def mock_gapfill_for_task(*args, **kwargs):
            raise RuntimeError("Infeasible")

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_gapfill_for_task", side_effect=mock_gapfill_for_task):
            result = await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        assert "T001" in result.infeasible_tasks

    @pytest.mark.asyncio
    async def test_task_results_before_after(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """Before and after task results are populated with correct phases."""
        mock_model = MagicMock()
        mock_universal = MagicMock()

        def make_results(model, tasks, progress_callback=None):
            """Return fresh TaskResult objects each call."""
            return [
                TaskResult(task=t, passed=True, actual_value=1.0) for t in tasks
            ]

        with patch.object(
            engine._task_runner, "run_all", side_effect=make_results
        ):
            result = await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        for r in result.task_results_before:
            assert r.phase == "before"
        for r in result.task_results_after:
            assert r.phase == "after"

    @pytest.mark.asyncio
    async def test_progress_callback(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """Progress callback is called with phase information."""
        mock_model = MagicMock()
        mock_universal = MagicMock()
        callback = MagicMock()

        before_results = [
            TaskResult(task=t, passed=True, actual_value=1.0) for t in sample_tasks
        ]

        with patch.object(
            engine._task_runner, "run_all", return_value=before_results
        ):
            await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
                progress_callback=callback,
            )

        # At minimum, testing_before and testing_after phases should be called
        phases_called = {call.args[0] for call in callback.call_args_list}
        assert "testing_before" in phases_called
        assert "testing_after" in phases_called

    @pytest.mark.asyncio
    async def test_gpr_assigned_to_added_reactions(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """GPR assigner is called for added reactions."""
        mock_model = MagicMock()
        mock_universal = MagicMock()

        # Setup: first task fails, triggers gap-fill
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        after_results = [
            TaskResult(task=sample_tasks[0], passed=True, actual_value=0.5),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]

        call_count = [0]

        def mock_run_all(model, tasks, progress_callback=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return before_results
            return after_results

        # Mock gapfill to return a reaction
        mock_rxn = MagicMock()
        mock_rxn.id = "GLNS"

        # Setup GPR assigner
        engine._gpr_assigner = MagicMock()
        engine._gpr_assigner.assign_batch = AsyncMock()

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_run_gapfill", new_callable=AsyncMock, return_value=[mock_rxn]), \
             patch.object(engine, "_apply_gapfill_results", return_value=[sample_candidates[0]]):
            await engine.run(
                mock_model,
                mock_universal,
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        engine._gpr_assigner.assign_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_and_close(self, engine: GapFillEngine) -> None:
        """Initialize sets up filter and assigner; close tears them down."""
        mock_cache = MagicMock()
        mock_mapping = MagicMock()

        with patch(
            "src.gapfill.engine.OrganismFilter"
        ) as MockFilter, patch(
            "src.gapfill.engine.GPRAssigner"
        ) as MockAssigner:
            mock_filter_inst = MagicMock()
            mock_filter_inst.initialize = AsyncMock()
            mock_filter_inst.close = AsyncMock()
            MockFilter.return_value = mock_filter_inst

            mock_assigner_inst = MagicMock()
            mock_assigner_inst.close = AsyncMock()
            MockAssigner.return_value = mock_assigner_inst

            await engine.initialize("eco", mock_cache, mock_mapping)

            assert engine._organism_filter is not None
            assert engine._gpr_assigner is not None
            mock_filter_inst.initialize.assert_called_once()

            await engine.close()

            mock_filter_inst.close.assert_called_once()
            mock_assigner_inst.close.assert_called_once()
            assert engine._organism_filter is None
            assert engine._gpr_assigner is None

    def test_apply_gapfill_results(
        self,
        engine: GapFillEngine,
        sample_candidates: list[CandidateReaction],
    ) -> None:
        """_apply_gapfill_results marks matching candidates as selected."""
        mock_model = MagicMock()
        mock_model.reactions = MagicMock()
        # Simulate that GLNS is not yet in the model
        mock_model.reactions.__contains__ = lambda self, x: False

        mock_rxn = MagicMock()
        mock_rxn.id = "GLNS"

        result = engine._apply_gapfill_results(
            mock_model, [mock_rxn], sample_candidates
        )

        assert len(result) == 1
        assert result[0].reaction.id == "GLNS"
        assert result[0].selected is True

    def test_gapfillable_task_filter(self, engine: GapFillEngine) -> None:
        """Only lower-bound production tasks should be sent to gap-fill."""
        positive = MetabolicTask(
            task_id="P",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">",
            expected_value=0.0,
        )
        lower_bound = MetabolicTask(
            task_id="GE",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">=",
            expected_value=1.0,
        )
        negative = MetabolicTask(
            task_id="N",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator="=",
            expected_value=0.0,
        )
        upper_bound = MetabolicTask(
            task_id="U",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator="<",
            expected_value=50.0,
        )

        assert engine._is_gapfillable_task(positive) is True
        assert engine._is_gapfillable_task(lower_bound) is True
        assert engine._is_gapfillable_task(negative) is False
        assert engine._is_gapfillable_task(upper_bound) is False

    def test_gapfill_disables_cobra_auto_demand_reactions(
        self, engine: GapFillEngine
    ) -> None:
        """Task objectives are explicit, so COBRApy demand auto-add must be off."""
        model = cobra.Model("draft")
        met = cobra.Metabolite("target_c", compartment="c")
        model.add_metabolites([met])
        universal = cobra.Model("universal")
        task = MetabolicTask(
            task_id="T",
            task_type="Metabolite",
            target_id="target_c",
            expected_operator=">",
            expected_value=0.0,
        )

        with patch(
            "src.gapfill.engine.cobra.flux_analysis.gapfilling.gapfill",
            return_value=[[]],
        ) as mock_gapfill:
            result = engine._gapfill_for_task(
                model, universal, task, penalties={}, lower_bound=0.05
            )

        assert result == []
        assert mock_gapfill.call_args.kwargs["demand_reactions"] is False

    def test_missing_reaction_task_target_is_preseeded_from_universal(
        self, engine: GapFillEngine
    ) -> None:
        """A removed reaction-task target is itself returned as gap-fill output."""
        model = cobra.Model("draft")
        a = cobra.Metabolite("a_c", compartment="c")
        b = cobra.Metabolite("b_c", compartment="c")
        model.add_metabolites([a, b])

        universal = cobra.Model("universal")
        rxn = cobra.Reaction("R_TARGET")
        rxn.add_metabolites({a.copy(): -1.0, b.copy(): 1.0})
        rxn.lower_bound = 0.0
        rxn.upper_bound = 1000.0
        universal.add_reactions([rxn])

        task = MetabolicTask(
            task_id="R",
            task_type="Reaction",
            target_id="R_TARGET",
            expected_operator=">",
            expected_value=0.0,
        )

        with patch(
            "src.gapfill.engine.cobra.flux_analysis.gapfilling.gapfill",
            return_value=[[]],
        ):
            result = engine._gapfill_for_task(
                model, universal, task, penalties={}, lower_bound=0.05
            )

        assert [r.id for r in result] == ["R_TARGET"]
        assert "R_TARGET" not in model.reactions

    def test_apply_gapfill_results_creates_fallback_candidate(
        self, engine: GapFillEngine
    ) -> None:
        """Reactions absent from the candidate table are still reported."""
        model = cobra.Model("draft")
        rxn = cobra.Reaction("EX_so4_e")
        rxn.lower_bound = -1000.0
        rxn.upper_bound = 1000.0

        result = engine._apply_gapfill_results(model, [rxn], candidates=[])

        assert len(result) == 1
        assert result[0].reaction.id == "EX_so4_e"
        assert result[0].source_model == "gapfill"
        assert result[0].selected is True
        assert "EX_so4_e" in model.reactions
        assert model.reactions.get_by_id("EX_so4_e") is not rxn

    def test_prune_universal_keeps_model_compatible_reactions_and_task_targets(
        self,
    ) -> None:
        """Large universals are pruned without dropping explicit task targets."""
        config = Config(
            gapfill_universal_prune_threshold=1,
            gapfill_prune_to_model_metabolites=True,
        )
        engine = GapFillEngine(config)

        model = cobra.Model("draft")
        a = cobra.Metabolite("a_c", compartment="c")
        b = cobra.Metabolite("b_c", compartment="c")
        model.add_metabolites([a, b])

        universal = cobra.Model("universal")
        keep = cobra.Reaction("R_KEEP")
        keep.add_metabolites({a.copy(): -1.0, b.copy(): 1.0})
        drop = cobra.Reaction("R_DROP")
        drop.add_metabolites(
            {
                cobra.Metabolite("x_c", compartment="c"): -1.0,
                cobra.Metabolite("y_c", compartment="c"): 1.0,
            }
        )
        target = cobra.Reaction("R_TARGET")
        target.add_metabolites(
            {
                cobra.Metabolite("x_c", compartment="c"): -1.0,
                cobra.Metabolite("z_c", compartment="c"): 1.0,
            }
        )
        universal.add_reactions([keep, drop, target])

        tasks = [
            MetabolicTask(
                task_id="T_TARGET",
                task_type="Reaction",
                target_id="R_TARGET",
                expected_operator=">",
                expected_value=0.0,
            )
        ]

        pruned = engine._prune_universal_for_gapfill(universal, model, tasks)

        assert pruned is not universal
        assert {rxn.id for rxn in pruned.reactions} == {"R_KEEP", "R_TARGET"}
        assert {rxn.id for rxn in universal.reactions} == {
            "R_KEEP",
            "R_DROP",
            "R_TARGET",
        }

    def test_lower_bound_for_strict_greater_uses_extra_tolerance(
        self, engine: GapFillEngine
    ) -> None:
        """Strict greater-than tasks need solver slack beyond the pass tolerance."""
        engine._config.gapfill_lower_bound = 0.0
        task = MetabolicTask(
            task_id="GT",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">",
            expected_value=1.0,
        )

        assert engine._lower_bound_for_task(task) == pytest.approx(1.000002)

    def test_retry_discards_subthreshold_solution(
        self, engine: GapFillEngine
    ) -> None:
        """Relaxed-bound retry must not keep reactions that fail the real check."""
        task = MetabolicTask(
            task_id="HI",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">=",
            expected_value=1.0,
        )
        result = GapFillResult(total_tasks=1)
        mock_rxn = MagicMock()
        mock_rxn.id = "R1"

        with patch.object(engine, "_gapfill_for_task", return_value=[mock_rxn]), \
             patch.object(engine, "_reactions_satisfy_task", return_value=False):
            out = engine._retry_gapfill(
                MagicMock(), MagicMock(), task, {}, required=1.0, result=result
            )

        assert out == []
        assert "HI" in result.infeasible_tasks

    def test_retry_keeps_passing_solution(self, engine: GapFillEngine) -> None:
        """Relaxed-bound retry keeps reactions that satisfy the real threshold."""
        task = MetabolicTask(
            task_id="HI",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">=",
            expected_value=1.0,
        )
        result = GapFillResult(total_tasks=1)
        mock_rxn = MagicMock()
        mock_rxn.id = "R1"

        with patch.object(engine, "_gapfill_for_task", return_value=[mock_rxn]), \
             patch.object(engine, "_reactions_satisfy_task", return_value=True):
            out = engine._retry_gapfill(
                MagicMock(), MagicMock(), task, {}, required=1.0, result=result
            )

        assert out == [mock_rxn]
        assert "HI" not in result.infeasible_tasks

    def test_retry_skips_when_no_relaxation_room(
        self, engine: GapFillEngine
    ) -> None:
        """When the requirement is already at the floor, no retry is attempted."""
        task = MetabolicTask(
            task_id="LO",
            task_type="Metabolite",
            target_id="atp_c",
            expected_operator=">",
            expected_value=0.0,
        )
        result = GapFillResult(total_tasks=1)

        with patch.object(engine, "_gapfill_for_task") as mock_gapfill:
            out = engine._retry_gapfill(
                MagicMock(), MagicMock(), task, {}, required=0.01, result=result
            )

        assert out == []
        mock_gapfill.assert_not_called()
        assert "LO" in result.infeasible_tasks

    @pytest.mark.asyncio
    async def test_protected_task_regression_rolls_back_iteration(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """A previously-passing task that fails after gap-fill is rolled back."""
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        after_results = [
            TaskResult(task=sample_tasks[0], passed=True, actual_value=1.0),
            TaskResult(task=sample_tasks[1], passed=False, actual_value=0.0),
        ]
        after_rollback = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        run_results = [before_results, after_results, after_rollback]

        def mock_run_all(model, tasks, progress_callback=None):
            return run_results.pop(0)

        model = cobra.Model("draft")
        mock_rxn = cobra.Reaction("GLNS")

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_run_gapfill", new_callable=AsyncMock, return_value=[mock_rxn]), \
             patch.object(engine, "_reactions_preserve_tasks", return_value=True):
            result = await engine.run(
                model,
                MagicMock(),
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        assert "GLNS" not in model.reactions
        assert result.added_reactions == []
        assert result.tasks_fixed == 0
        assert result.tasks_broken == 0

    @pytest.mark.asyncio
    async def test_run_gapfill_discards_solution_that_breaks_protected_task(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
    ) -> None:
        """Per-task gap-fill candidates are rejected if protected tasks fail."""
        task_to_fix = sample_tasks[0]
        protected = [sample_tasks[1]]
        result = GapFillResult(total_tasks=2)
        mock_rxn = cobra.Reaction("NH4t")

        with patch.object(engine, "_gapfill_for_task", return_value=[mock_rxn]), \
             patch.object(engine, "_reactions_preserve_tasks", return_value=False):
            added = await engine._run_gapfill(
                cobra.Model("draft"),
                cobra.Model("universal"),
                [task_to_fix],
                penalties={},
                result=result,
                protected_tasks=protected,
            )

        assert added == []
        assert task_to_fix.task_id in result.infeasible_tasks

    @pytest.mark.asyncio
    async def test_loop_stops_without_net_progress(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """Iteration loop halts when passing-task count does not improve."""
        engine._config.gapfill_iterations = 5
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        # No improvement after gap-fill: same pass/fail pattern as before.
        after_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        call_count = [0]

        def mock_run_all(model, tasks, progress_callback=None):
            call_count[0] += 1
            return before_results if call_count[0] == 1 else after_results

        mock_rxn = MagicMock()
        mock_rxn.id = "GLNS"
        gapfill_mock = AsyncMock(return_value=[mock_rxn])

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_run_gapfill", gapfill_mock), \
             patch.object(engine, "_apply_gapfill_results", return_value=[sample_candidates[0]]):
            await engine.run(
                MagicMock(),
                MagicMock(),
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        # Despite gapfill_iterations=5, the no-progress guard stops after one
        # gap-fill round instead of looping five times.
        assert gapfill_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_no_progress_iteration_rolls_back_added_reactions(
        self,
        engine: GapFillEngine,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
        sample_evidence: dict[str, ReactionEvidence],
    ) -> None:
        """No-progress gap-fill additions are removed before returning."""
        engine._config.gapfill_iterations = 5
        before_results = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        after_no_progress = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        after_rollback = [
            TaskResult(task=sample_tasks[0], passed=False, actual_value=0.0),
            TaskResult(task=sample_tasks[1], passed=True, actual_value=1.0),
        ]
        run_results = [before_results, after_no_progress, after_rollback]

        def mock_run_all(model, tasks, progress_callback=None):
            return run_results.pop(0)

        model = cobra.Model("draft")
        rxn = cobra.Reaction("GLNS")
        gapfill_mock = AsyncMock(return_value=[rxn])

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(engine, "_run_gapfill", gapfill_mock):
            result = await engine.run(
                model,
                MagicMock(),
                sample_candidates,
                sample_tasks,
                sample_evidence,
            )

        assert "GLNS" not in model.reactions
        assert result.added_reactions == []
        assert result.tasks_fixed == 0
        assert result.tasks_broken == 0
        assert sample_candidates[0].selected is False
