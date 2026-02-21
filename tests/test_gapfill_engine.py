"""Tests for GapFillEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
            result = await engine.run(
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
