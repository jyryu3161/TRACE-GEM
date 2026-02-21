"""Integration tests for the gap-filling pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli import _build_parser, _save_gapfill_report, async_gapfill_main
from src.core.models import (
    CandidateReaction,
    GapFillResult,
    MetabolicTask,
    ModelData,
    Reaction,
    ReactionEvidence,
    TaskResult,
)
from src.core.task_parser import TaskRunner
from src.core.universal_loader import UniversalLoader
from src.gapfill.engine import GapFillEngine
from src.utils.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> Config:
    return Config(
        kegg_organism_code="eco",
        organism_name="Escherichia coli",
        gapfill_lower_bound=0.05,
        gapfill_penalty_epsilon=0.01,
        gapfill_organism_penalty_multiplier=10.0,
        gapfill_no_kegg_penalty_multiplier=2.0,
    )


@pytest.fixture
def sample_model_data() -> ModelData:
    return ModelData(
        id="test_model",
        name="Test Model",
        reactions=[
            Reaction(id="ENO", name="enolase", equation="2pg <=> pep + h2o"),
            Reaction(id="PFK", name="phosphofructokinase", equation="atp + f6p -> adp + fdp"),
            Reaction(id="EX_glc__D_e", name="Glucose exchange", equation="glc__D_e -->"),
        ],
        organism="Escherichia coli",
        kegg_organism_code="eco",
        cobra_model=MagicMock(),
    )


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
            task_type="Reaction",
            target_id="ENO",
            expected_operator=">",
            expected_value=0.0,
            description="ENO flux",
            category="Glycolysis",
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
    ]


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------


class TestCLIGapFillMode:
    def test_gap_fill_flag_parsed(self) -> None:
        """--gap-fill flag is parsed correctly."""
        parser = _build_parser()
        args = parser.parse_args(["model.xml", "--gap-fill"])
        assert args.gap_fill is True

    def test_gap_fill_all_args(self) -> None:
        """All gap-fill arguments are parsed correctly."""
        parser = _build_parser()
        args = parser.parse_args([
            "model.xml",
            "--gap-fill",
            "--organism", "eco",
            "--universal", "/path/to/universal.json",
            "--tasks", "/path/to/tasks.csv",
            "--output-model", "/path/to/improved.xml",
            "--output-report", "/path/to/report.csv",
            "--skip-evaluation",
        ])
        assert args.gap_fill is True
        assert args.organism == "eco"
        assert args.universal == "/path/to/universal.json"
        assert args.tasks == "/path/to/tasks.csv"
        assert args.output_model == "/path/to/improved.xml"
        assert args.output_report == "/path/to/report.csv"
        assert args.skip_evaluation is True

    def test_gap_fill_defaults(self) -> None:
        """Gap-fill arguments have correct defaults."""
        parser = _build_parser()
        args = parser.parse_args(["model.xml", "--gap-fill"])
        assert args.universal is None
        assert args.tasks is None
        assert args.output_model is None
        assert args.output_report is None
        assert args.skip_evaluation is False

    def test_gap_fill_not_set(self) -> None:
        """Without --gap-fill, flag is False."""
        parser = _build_parser()
        args = parser.parse_args(["model.xml"])
        assert args.gap_fill is False


# ---------------------------------------------------------------------------
# E2E pipeline test with mocked dependencies
# ---------------------------------------------------------------------------


class TestE2EWithMiniModel:
    @pytest.mark.asyncio
    async def test_e2e_pipeline(
        self,
        config: Config,
        sample_model_data: ModelData,
        sample_tasks: list[MetabolicTask],
        sample_candidates: list[CandidateReaction],
    ) -> None:
        """Full gap-fill pipeline with mocked cobra model and APIs."""
        engine = GapFillEngine(config)

        # Task T001 fails before, passes after; T002 passes both times
        call_count = [0]

        def mock_run_all(model, tasks, progress_callback=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # Before: T001 fails
                return [
                    TaskResult(task=tasks[0], passed=False, actual_value=0.0),
                    TaskResult(task=tasks[1], passed=True, actual_value=1.0),
                ]
            # After: both pass
            return [
                TaskResult(task=tasks[0], passed=True, actual_value=0.5),
                TaskResult(task=tasks[1], passed=True, actual_value=1.0),
            ]

        # Mock gap-fill to return a reaction
        mock_rxn = MagicMock()
        mock_rxn.id = "GLNS"

        with patch.object(engine._task_runner, "run_all", side_effect=mock_run_all), \
             patch.object(
                 engine, "_gapfill_for_task", return_value=[mock_rxn]
             ), \
             patch.object(
                 engine, "_apply_gapfill_results",
                 return_value=[sample_candidates[0]],
             ):
            result = await engine.run(
                user_model=sample_model_data.cobra_model,
                universal_model=MagicMock(),
                candidates=sample_candidates,
                tasks=sample_tasks,
                evidence_results={},
            )

        assert result.total_tasks == 2
        assert result.tasks_fixed == 1
        assert len(result.added_reactions) == 1
        assert result.added_reactions[0].reaction.id == "GLNS"

        # Verify before/after phases
        assert all(r.phase == "before" for r in result.task_results_before)
        assert all(r.phase == "after" for r in result.task_results_after)


# ---------------------------------------------------------------------------
# Task before/after comparison tests
# ---------------------------------------------------------------------------


class TestTaskBeforeAfterComparison:
    def test_tasks_fixed_count(self) -> None:
        """tasks_fixed correctly counts transitions from fail to pass."""
        tasks = [
            MetabolicTask(task_id=f"T{i:03d}", task_type="Reaction", target_id=f"RXN{i}")
            for i in range(4)
        ]

        before = [
            TaskResult(task=tasks[0], passed=False, actual_value=0.0),  # -> PASS (fixed)
            TaskResult(task=tasks[1], passed=False, actual_value=0.0),  # -> FAIL (still failing)
            TaskResult(task=tasks[2], passed=True, actual_value=1.0),   # -> PASS (ok)
            TaskResult(task=tasks[3], passed=True, actual_value=1.0),   # -> FAIL (regression)
        ]
        after = [
            TaskResult(task=tasks[0], passed=True, actual_value=0.5),
            TaskResult(task=tasks[1], passed=False, actual_value=0.0),
            TaskResult(task=tasks[2], passed=True, actual_value=1.0),
            TaskResult(task=tasks[3], passed=False, actual_value=0.0),
        ]

        before_failed = {r.task.task_id for r in before if not r.passed}
        after_passed = {r.task.task_id for r in after if r.passed}
        tasks_fixed = len(before_failed & after_passed)

        assert tasks_fixed == 1  # Only T000 went from fail to pass
        assert before_failed == {"T000", "T001"}
        assert after_passed == {"T000", "T002"}

    def test_save_gapfill_report(self, tmp_path) -> None:
        """_save_gapfill_report writes valid CSV with all sections."""
        tasks = [
            MetabolicTask(
                task_id="T001",
                task_type="Reaction",
                target_id="PFK",
                description="PFK flux",
                category="Glycolysis",
            ),
        ]

        result = GapFillResult(
            added_reactions=[
                CandidateReaction(
                    reaction=Reaction(
                        id="GLNS",
                        name="Glutamine synthetase",
                        equation="glu -> gln",
                        subsystem="Amino Acid",
                    ),
                    penalty=1.5,
                    assigned_gpr="b0485",
                ),
            ],
            task_results_before=[
                TaskResult(task=tasks[0], passed=False, actual_value=0.0, phase="before"),
            ],
            task_results_after=[
                TaskResult(task=tasks[0], passed=True, actual_value=0.5, phase="after"),
            ],
            tasks_fixed=1,
            total_tasks=1,
            iterations=1,
        )

        report_path = str(tmp_path / "report.csv")
        _save_gapfill_report(report_path, result, tasks)

        import csv
        with open(report_path) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check summary section
        assert rows[0] == ["Gap-Fill Summary"]
        assert rows[1] == ["Reactions Added", "1"]
        assert rows[2] == ["Tasks Fixed", "1"]

        # Check added reactions section
        added_header_idx = next(i for i, r in enumerate(rows) if r == ["Added Reactions"])
        assert rows[added_header_idx + 1][0] == "Reaction ID"
        assert rows[added_header_idx + 2][0] == "GLNS"

        # Check task results section
        task_header_idx = next(i for i, r in enumerate(rows) if r == ["Task Results"])
        assert rows[task_header_idx + 1][0] == "Task ID"
        task_row = rows[task_header_idx + 2]
        assert task_row[0] == "T001"
        assert task_row[5] == "False"  # Before Pass
        assert task_row[7] == "True"   # After Pass
        assert task_row[9] == "FIXED"  # Status

    def test_infeasible_tasks_in_result(self) -> None:
        """Infeasible tasks are tracked separately from failing tasks."""
        result = GapFillResult(
            total_tasks=3,
            infeasible_tasks=["T002"],
            tasks_fixed=0,
        )
        assert "T002" in result.infeasible_tasks
        assert result.total_tasks == 3
