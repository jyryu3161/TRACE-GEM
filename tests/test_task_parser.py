"""Tests for metabolic task parser and runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.models import MetabolicTask
from src.core.task_parser import TaskParser, TaskRunner

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TASK_CSV = DATA_DIR / "universal_essential_tasks.csv"


# ---------------------------------------------------------------------------
# TaskParser tests
# ---------------------------------------------------------------------------


class TestTaskParserParseCSV:
    def test_parse_csv_basic(self):
        """Parse the actual universal_essential_tasks.csv and verify structure."""
        parser = TaskParser()
        tasks = parser.parse(TASK_CSV)

        assert len(tasks) > 0
        # First task should be U001
        first = tasks[0]
        assert first.task_id == "U001"
        assert first.task_type == "Metabolite"
        assert first.target_id == "atp_c"
        assert first.expected_operator == ">"
        assert first.expected_value == 0.0
        assert first.category == "Energy"
        assert "ATP" in first.description

        # Check medium was parsed
        assert "EX_glc__D_e" in first.medium
        assert first.medium["EX_glc__D_e"] == -10.0

        # Check constraints were parsed
        assert "EX_o2_e" in first.constraints
        assert first.constraints["EX_o2_e"] == (-1000.0, 1000.0)

    def test_parse_csv_all_rows(self):
        """All rows in the CSV should parse without errors."""
        parser = TaskParser()
        tasks = parser.parse(TASK_CSV)
        # The CSV has 52 data rows (U001-U052)
        assert len(tasks) == 52

    def test_parse_csv_reaction_type(self):
        """Verify Reaction-type tasks are parsed correctly."""
        parser = TaskParser()
        tasks = parser.parse(TASK_CSV)
        reaction_tasks = [t for t in tasks if t.task_type == "Reaction"]
        assert len(reaction_tasks) > 0
        # U036 is ATPM
        atpm = next(t for t in tasks if t.task_id == "U036")
        assert atpm.task_type == "Reaction"
        assert atpm.target_id == "ATPM"

    def test_parse_csv_negative_constraint(self):
        """Verify tasks with =0.0 expected value (negative constraints)."""
        parser = TaskParser()
        tasks = parser.parse(TASK_CSV)
        neg = [t for t in tasks if t.expected_operator == "=" and t.expected_value == 0.0]
        assert len(neg) > 0
        # U041 expects =0.0
        u041 = next(t for t in tasks if t.task_id == "U041")
        assert u041.expected_operator == "="
        assert u041.expected_value == 0.0


class TestParseMedium:
    def test_single_entry(self):
        parser = TaskParser()
        result = parser._parse_medium("glc__D_e(-10.0)")
        assert result == {"EX_glc__D_e": -10.0}

    def test_multiple_entries(self):
        parser = TaskParser()
        result = parser._parse_medium("glc__D_e(-10.0);o2_e(-1000.0);pi_e(-1000.0)")
        assert result == {
            "EX_glc__D_e": -10.0,
            "EX_o2_e": -1000.0,
            "EX_pi_e": -1000.0,
        }

    def test_empty_string(self):
        parser = TaskParser()
        assert parser._parse_medium("") == {}

    def test_negative_values(self):
        parser = TaskParser()
        result = parser._parse_medium("nh4_e(-1000.0)")
        assert result == {"EX_nh4_e": -1000.0}

    def test_zero_value(self):
        parser = TaskParser()
        result = parser._parse_medium("o2_e(0.0)")
        assert result == {"EX_o2_e": 0.0}


class TestParseConstraints:
    def test_single_constraint(self):
        parser = TaskParser()
        result = parser._parse_constraints("EX_o2_e(-1000.0#1000.0)")
        assert result == {"EX_o2_e": (-1000.0, 1000.0)}

    def test_zero_bounds(self):
        parser = TaskParser()
        result = parser._parse_constraints("EX_o2_e(0.0#0.0)")
        assert result == {"EX_o2_e": (0.0, 0.0)}

    def test_empty_string(self):
        parser = TaskParser()
        assert parser._parse_constraints("") == {}

    def test_multiple_constraints(self):
        parser = TaskParser()
        result = parser._parse_constraints("EX_o2_e(-1000.0#1000.0);EX_glc__D_e(-10.0#0.0)")
        assert result == {
            "EX_o2_e": (-1000.0, 1000.0),
            "EX_glc__D_e": (-10.0, 0.0),
        }


class TestParseExpected:
    def test_greater_than(self):
        parser = TaskParser()
        assert parser._parse_expected(">0.0") == (">", 0.0)

    def test_less_than(self):
        parser = TaskParser()
        assert parser._parse_expected("<50.0") == ("<", 50.0)

    def test_equal(self):
        parser = TaskParser()
        assert parser._parse_expected("=0.0") == ("=", 0.0)

    def test_greater_equal(self):
        parser = TaskParser()
        assert parser._parse_expected(">=1.0") == (">=", 1.0)

    def test_less_equal(self):
        parser = TaskParser()
        assert parser._parse_expected("<=10.0") == ("<=", 10.0)

    def test_invalid_format(self):
        parser = TaskParser()
        with pytest.raises(ValueError, match="Invalid expected value format"):
            parser._parse_expected("abc")


# ---------------------------------------------------------------------------
# TaskRunner tests
# ---------------------------------------------------------------------------


def _make_mock_model(reactions: dict[str, MagicMock], metabolites: dict[str, MagicMock] | None = None):
    """Create a mock cobra.Model with specified reactions and metabolites."""
    model = MagicMock(spec=["copy", "reactions", "metabolites", "optimize", "objective", "add_reactions"])

    # Reactions container
    rxn_container = MagicMock()
    rxn_list = list(reactions.values())
    rxn_container.__iter__ = lambda self: iter(rxn_list)

    def get_rxn_by_id(rxn_id):
        if rxn_id in reactions:
            return reactions[rxn_id]
        raise KeyError(rxn_id)

    rxn_container.get_by_id = get_rxn_by_id
    model.reactions = rxn_container

    # Metabolites container
    met_container = MagicMock()
    if metabolites:
        def get_met_by_id(met_id):
            if met_id in metabolites:
                return metabolites[met_id]
            raise KeyError(met_id)
        met_container.get_by_id = get_met_by_id
    else:
        met_container.get_by_id = MagicMock(side_effect=KeyError)
    model.metabolites = met_container

    # Copy returns itself (we track mutations on the mock directly)
    model.copy.return_value = model

    # Default optimize result
    solution = MagicMock()
    solution.status = "optimal"
    solution.objective_value = 10.0
    model.optimize.return_value = solution

    # add_reactions just records calls
    model.add_reactions = MagicMock()

    return model


def _make_mock_reaction(rxn_id: str, is_exchange: bool = False):
    """Create a mock reaction with settable bounds."""
    rxn = MagicMock()
    rxn.id = rxn_id
    rxn.lower_bound = -1000.0 if not is_exchange else -10.0
    rxn.upper_bound = 1000.0
    # Make startswith work for exchange detection
    rxn.id_startswith = rxn_id.startswith
    return rxn


class TestRunTaskMetaboliteType:
    def test_metabolite_task_passes(self):
        """A Metabolite-type task that finds its target and gets flux > 0."""
        # Build mock model
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        ex_o2 = _make_mock_reaction("EX_o2_e", is_exchange=True)
        atp_met = MagicMock()
        atp_met.id = "atp_c"

        reactions = {"EX_glc__D_e": ex_glc, "EX_o2_e": ex_o2}
        metabolites = {"atp_c": atp_met}
        model = _make_mock_model(reactions, metabolites)

        task = MetabolicTask(
            task_id="U001",
            task_type="Metabolite",
            target_id="atp_c",
            medium={"EX_glc__D_e": -10.0, "EX_o2_e": -1000.0},
            constraints={"EX_o2_e": (-1000.0, 1000.0)},
            expected_operator=">",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is True
        assert result.actual_value == 10.0
        assert result.error_message is None

    def test_metabolite_not_found(self):
        """A Metabolite-type task where the target metabolite is missing."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        reactions = {"EX_glc__D_e": ex_glc}
        model = _make_mock_model(reactions, metabolites={})

        # Metabolites get_by_id raises KeyError for missing
        model.metabolites.get_by_id = MagicMock(side_effect=KeyError("missing_c"))

        task = MetabolicTask(
            task_id="T001",
            task_type="Metabolite",
            target_id="missing_c",
            medium={},
            expected_operator=">",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is False
        assert "not found" in result.error_message


class TestRunTaskReactionType:
    def test_reaction_task_passes(self):
        """A Reaction-type task that optimizes the target reaction."""
        atpm = _make_mock_reaction("ATPM")
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        ex_o2 = _make_mock_reaction("EX_o2_e", is_exchange=True)

        reactions = {"ATPM": atpm, "EX_glc__D_e": ex_glc, "EX_o2_e": ex_o2}
        model = _make_mock_model(reactions)

        task = MetabolicTask(
            task_id="U036",
            task_type="Reaction",
            target_id="ATPM",
            medium={"EX_glc__D_e": -10.0, "EX_o2_e": -1000.0},
            constraints={"EX_o2_e": (-1000.0, 1000.0)},
            expected_operator=">",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is True
        assert result.actual_value == 10.0

    def test_reaction_not_found(self):
        """A Reaction-type task where the target reaction is missing."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        reactions = {"EX_glc__D_e": ex_glc}
        model = _make_mock_model(reactions)

        task = MetabolicTask(
            task_id="T002",
            task_type="Reaction",
            target_id="MISSING_RXN",
            medium={},
            expected_operator=">",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is False
        assert "not found" in result.error_message


class TestRunTaskNegativeConstraint:
    def test_expected_zero_passes(self):
        """A task with =0.0 expected (negative constraint) passes when flux is 0."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        atp_met = MagicMock()
        atp_met.id = "atp_c"

        reactions = {"EX_glc__D_e": ex_glc}
        metabolites = {"atp_c": atp_met}
        model = _make_mock_model(reactions, metabolites)

        # Optimize returns 0.0 (no flux without carbon source)
        solution = MagicMock()
        solution.status = "optimal"
        solution.objective_value = 0.0
        model.optimize.return_value = solution

        task = MetabolicTask(
            task_id="U041",
            task_type="Metabolite",
            target_id="atp_c",
            medium={"EX_glc__D_e": -10.0},
            expected_operator="=",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is True
        assert abs(result.actual_value) < 1e-6

    def test_expected_zero_fails_with_flux(self):
        """A negative constraint fails when there is unexpected flux."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        atp_met = MagicMock()
        atp_met.id = "atp_c"

        reactions = {"EX_glc__D_e": ex_glc}
        metabolites = {"atp_c": atp_met}
        model = _make_mock_model(reactions, metabolites)

        # Optimize returns positive flux (unexpected)
        solution = MagicMock()
        solution.status = "optimal"
        solution.objective_value = 5.0
        model.optimize.return_value = solution

        task = MetabolicTask(
            task_id="U041",
            task_type="Metabolite",
            target_id="atp_c",
            medium={},
            expected_operator="=",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        assert result.passed is False
        assert result.actual_value == 5.0


class TestRunTaskInfeasible:
    def test_infeasible_solution(self):
        """When optimization is infeasible, actual_value should be 0."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        atp_met = MagicMock()
        atp_met.id = "atp_c"

        reactions = {"EX_glc__D_e": ex_glc}
        metabolites = {"atp_c": atp_met}
        model = _make_mock_model(reactions, metabolites)

        solution = MagicMock()
        solution.status = "infeasible"
        solution.objective_value = None
        model.optimize.return_value = solution

        task = MetabolicTask(
            task_id="T003",
            task_type="Metabolite",
            target_id="atp_c",
            medium={},
            expected_operator=">",
            expected_value=0.0,
        )

        runner = TaskRunner()
        result = runner.run_task(model, task)

        # >0.0 with tolerance means actual > -1e-6, so 0.0 passes
        # But the intent of infeasible is that it truly produces nothing
        assert result.actual_value == 0.0


class TestCheckExpected:
    def setup_method(self):
        self.runner = TaskRunner()

    def test_greater_than_passes(self):
        assert self.runner._check_expected(1.0, ">", 0.0) is True

    def test_greater_than_fails(self):
        assert self.runner._check_expected(-1.0, ">", 0.0) is False

    def test_less_than_passes(self):
        assert self.runner._check_expected(10.0, "<", 50.0) is True

    def test_less_than_fails(self):
        assert self.runner._check_expected(100.0, "<", 50.0) is False

    def test_equal_passes(self):
        assert self.runner._check_expected(0.0, "=", 0.0) is True

    def test_equal_fails(self):
        assert self.runner._check_expected(1.0, "=", 0.0) is False

    def test_greater_equal(self):
        assert self.runner._check_expected(5.0, ">=", 5.0) is True
        assert self.runner._check_expected(4.0, ">=", 5.0) is False

    def test_less_equal(self):
        assert self.runner._check_expected(5.0, "<=", 5.0) is True
        assert self.runner._check_expected(6.0, "<=", 5.0) is False

    def test_tolerance_boundary(self):
        """Values within tolerance of the boundary should pass."""
        # 0.0 > 0.0 with tolerance: 0.0 > -1e-6 → True
        assert self.runner._check_expected(0.0, ">", 0.0) is True
        # Very slightly negative but within tolerance
        assert self.runner._check_expected(-1e-7, ">", 0.0) is True
        # Outside tolerance
        assert self.runner._check_expected(-1e-5, ">", 0.0) is False


class TestRunAll:
    def test_run_all_basic(self):
        """run_all processes multiple tasks and calls progress callback."""
        ex_glc = _make_mock_reaction("EX_glc__D_e", is_exchange=True)
        atp_met = MagicMock()
        atp_met.id = "atp_c"

        reactions = {"EX_glc__D_e": ex_glc}
        metabolites = {"atp_c": atp_met}
        model = _make_mock_model(reactions, metabolites)

        tasks = [
            MetabolicTask(
                task_id="T1",
                task_type="Metabolite",
                target_id="atp_c",
                medium={},
                expected_operator=">",
                expected_value=0.0,
            ),
            MetabolicTask(
                task_id="T2",
                task_type="Metabolite",
                target_id="atp_c",
                medium={},
                expected_operator="=",
                expected_value=0.0,
            ),
        ]

        progress_calls = []
        def on_progress(current, total, msg):
            progress_calls.append((current, total, msg))

        runner = TaskRunner()
        results = runner.run_all(model, tasks, progress_callback=on_progress)

        assert len(results) == 2
        # First task (>0.0 with value=10.0) should pass
        assert results[0].passed is True
        # Second task (=0.0 with value=10.0) should fail
        assert results[1].passed is False
        # Progress was called for each task + final
        assert len(progress_calls) == 3
        assert progress_calls[-1][0] == progress_calls[-1][1]  # final: current == total
