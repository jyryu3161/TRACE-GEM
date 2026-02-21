"""Metabolic task CSV parser and FBA-based task runner."""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from pathlib import Path

import cobra

from src.core.models import MetabolicTask, TaskResult

logger = logging.getLogger(__name__)


class TaskParser:
    """Parse metabolic task definitions from CSV files."""

    def parse(self, filepath: str | Path) -> list[MetabolicTask]:
        """Read a CSV file and return a list of MetabolicTask objects.

        CSV columns: Task ID, Type, ID, Medium, Constraints, Expected value,
                     Description, Category
        """
        filepath = Path(filepath)
        tasks: list[MetabolicTask] = []

        with filepath.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                operator, value = self._parse_expected(row["Expected value"].strip())
                task = MetabolicTask(
                    task_id=row["Task ID"].strip(),
                    task_type=row["Type"].strip(),
                    target_id=row["ID"].strip(),
                    medium=self._parse_medium(row["Medium"].strip()),
                    constraints=self._parse_constraints(row["Constraints"].strip()),
                    expected_operator=operator,
                    expected_value=value,
                    description=row["Description"].strip(),
                    category=row["Category"].strip(),
                )
                tasks.append(task)

        logger.info("Parsed %d metabolic tasks from %s", len(tasks), filepath)
        return tasks

    def _parse_medium(self, medium_str: str) -> dict[str, float]:
        """Parse medium string into exchange reaction bounds.

        Input:  "glc__D_e(-10.0);o2_e(-1000.0)"
        Output: {"EX_glc__D_e": -10.0, "EX_o2_e": -1000.0}
        """
        if not medium_str:
            return {}

        medium: dict[str, float] = {}
        for entry in medium_str.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            match = re.match(r"^(.+?)\(([^)]+)\)$", entry)
            if match:
                met_id = match.group(1)
                bound = float(match.group(2))
                medium[f"EX_{met_id}"] = bound
            else:
                logger.warning("Could not parse medium entry: %s", entry)
        return medium

    def _parse_constraints(
        self, constraint_str: str
    ) -> dict[str, tuple[float, float]]:
        """Parse constraint string into reaction bound tuples.

        Input:  "EX_o2_e(-1000.0#1000.0)"
        Output: {"EX_o2_e": (-1000.0, 1000.0)}
        """
        if not constraint_str:
            return {}

        constraints: dict[str, tuple[float, float]] = {}
        for entry in constraint_str.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            match = re.match(r"^(.+?)\(([^#]+)#([^)]+)\)$", entry)
            if match:
                rxn_id = match.group(1)
                lower = float(match.group(2))
                upper = float(match.group(3))
                constraints[rxn_id] = (lower, upper)
            else:
                logger.warning("Could not parse constraint entry: %s", entry)
        return constraints

    def _parse_expected(self, expected_str: str) -> tuple[str, float]:
        """Parse expected value string into operator and numeric value.

        Input:  ">0.0", "<50.0", "=0.0", ">=1.0", "<=10.0"
        Output: (">", 0.0), ("<", 50.0), ("=", 0.0), (">=", 1.0), ("<=", 10.0)
        """
        match = re.match(r"^(>=|<=|>|<|=)(.+)$", expected_str)
        if not match:
            raise ValueError(f"Invalid expected value format: {expected_str}")
        operator = match.group(1)
        value = float(match.group(2))
        return operator, value


class TaskRunner:
    """Run metabolic tasks against a COBRA model using FBA."""

    _TOLERANCE = 1e-6

    def run_task(self, model: cobra.Model, task: MetabolicTask) -> TaskResult:
        """Run a single metabolic task and return the result.

        Steps:
        1. Copy model to avoid side effects
        2. Close all exchange reactions (lower_bound = 0)
        3. Apply medium bounds
        4. Apply additional constraints
        5. Set objective based on task type
        6. Optimize and compare with expected value
        """
        test_model = model.copy()
        demand_rxn_id: str | None = None

        try:
            # Close all exchange reactions
            for rxn in test_model.reactions:
                if rxn.id.startswith("EX_"):
                    rxn.lower_bound = 0.0

            # Apply medium
            self._apply_medium(test_model, task.medium)

            # Apply constraints
            self._apply_constraints(test_model, task.constraints)

            # Set objective based on task type
            if task.task_type == "Metabolite":
                demand_rxn_id = f"DM_{task.target_id}"
                try:
                    met = test_model.metabolites.get_by_id(task.target_id)
                except KeyError:
                    return TaskResult(
                        task=task,
                        passed=False,
                        actual_value=0.0,
                        error_message=f"Metabolite '{task.target_id}' not found in model",
                    )
                demand_rxn = cobra.Reaction(demand_rxn_id)
                demand_rxn.add_metabolites({met: -1.0})
                demand_rxn.lower_bound = 0.0
                demand_rxn.upper_bound = 1000.0
                test_model.add_reactions([demand_rxn])
                test_model.objective = demand_rxn_id
            elif task.task_type == "Reaction":
                try:
                    test_model.reactions.get_by_id(task.target_id)
                except KeyError:
                    return TaskResult(
                        task=task,
                        passed=False,
                        actual_value=0.0,
                        error_message=f"Reaction '{task.target_id}' not found in model",
                    )
                test_model.objective = task.target_id
            else:
                return TaskResult(
                    task=task,
                    passed=False,
                    actual_value=0.0,
                    error_message=f"Unknown task type: {task.task_type}",
                )

            # Optimize
            solution = test_model.optimize()

            if solution.status == "infeasible":
                actual = 0.0
            else:
                actual = solution.objective_value if solution.objective_value is not None else 0.0

            passed = self._check_expected(actual, task.expected_operator, task.expected_value)

            return TaskResult(task=task, passed=passed, actual_value=actual)

        except Exception as exc:
            logger.error("Error running task %s: %s", task.task_id, exc)
            return TaskResult(
                task=task,
                passed=False,
                actual_value=0.0,
                error_message=str(exc),
            )

    def run_all(
        self,
        model: cobra.Model,
        tasks: list[MetabolicTask],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[TaskResult]:
        """Run all metabolic tasks sequentially.

        Each task runs on an independent model copy.
        """
        results: list[TaskResult] = []
        total = len(tasks)

        for i, task in enumerate(tasks):
            if progress_callback:
                progress_callback(i, total, f"Running task {task.task_id}")
            result = self.run_task(model, task)
            results.append(result)
            logger.debug(
                "Task %s: %s (actual=%.6f)",
                task.task_id,
                "PASS" if result.passed else "FAIL",
                result.actual_value,
            )

        if progress_callback:
            progress_callback(total, total, "Complete")

        passed = sum(1 for r in results if r.passed)
        logger.info("Task results: %d/%d passed", passed, total)
        return results

    def _apply_medium(self, model: cobra.Model, medium: dict[str, float]) -> None:
        """Set exchange reaction bounds according to medium specification."""
        for rxn_id, lower_bound in medium.items():
            try:
                rxn = model.reactions.get_by_id(rxn_id)
                rxn.lower_bound = lower_bound
            except KeyError:
                logger.warning("Exchange reaction '%s' not found in model", rxn_id)

    def _apply_constraints(
        self, model: cobra.Model, constraints: dict[str, tuple[float, float]]
    ) -> None:
        """Apply additional bound constraints to reactions."""
        for rxn_id, (lower, upper) in constraints.items():
            try:
                rxn = model.reactions.get_by_id(rxn_id)
                rxn.lower_bound = lower
                rxn.upper_bound = upper
            except KeyError:
                logger.warning("Reaction '%s' not found for constraint", rxn_id)

    def _check_expected(
        self, actual: float, operator: str, expected: float
    ) -> bool:
        """Check whether actual value satisfies the expected condition.

        Operators: >, <, =, >=, <=
        Uses tolerance of 1e-6 for floating-point comparison.
        """
        tol = self._TOLERANCE
        if operator == ">":
            return actual > expected - tol
        elif operator == "<":
            return actual < expected + tol
        elif operator == "=":
            return abs(actual - expected) < tol
        elif operator == ">=":
            return actual >= expected - tol
        elif operator == "<=":
            return actual <= expected + tol
        else:
            logger.warning("Unknown operator: %s", operator)
            return False
