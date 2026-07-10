"""Metabolic task CSV parser and FBA-based task runner."""

from __future__ import annotations

import csv
import io
import logging
import math
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
        raw_lines = filepath.read_text(encoding="utf-8-sig").splitlines()
        background_medium: dict[str, float] = {}
        csv_lines: list[str] = []
        for line in raw_lines:
            if line.startswith("# Background medium:"):
                if background_medium:
                    raise ValueError("Task CSV defines more than one background medium")
                background_medium = self._parse_medium(line.split(":", 1)[1].strip())
                continue
            if line.startswith("#") or not line.strip():
                continue
            csv_lines.append(line)
        if not csv_lines:
            raise ValueError(f"Task CSV contains no header or tasks: {filepath}")

        required_columns = {
            "Task ID",
            "Type",
            "ID",
            "Medium",
            "Constraints",
            "Expected value",
            "Description",
            "Category",
        }
        seen_task_ids: set[str] = set()

        with io.StringIO("\n".join(csv_lines), newline="") as fh:
            reader = csv.DictReader(fh)
            missing_columns = required_columns - set(reader.fieldnames or [])
            if missing_columns:
                raise ValueError(
                    "Task CSV is missing required column(s): " + ", ".join(sorted(missing_columns))
                )

            for line_number, row in enumerate(reader, start=2):
                task_id = row["Task ID"].strip()
                task_type = row["Type"].strip()
                target_id = row["ID"].strip()
                if not task_id:
                    raise ValueError(f"Line {line_number}: Task ID must not be empty")
                if task_id in seen_task_ids:
                    raise ValueError(f"Line {line_number}: duplicate Task ID '{task_id}'")
                if task_type not in {"Metabolite", "Reaction"}:
                    raise ValueError(
                        f"Line {line_number}: Type must be Metabolite or Reaction, "
                        f"got '{task_type}'"
                    )
                if not target_id:
                    raise ValueError(f"Line {line_number}: ID must not be empty")

                operator, value = self._parse_expected(row["Expected value"].strip())
                task_medium = dict(background_medium)
                task_medium.update(self._parse_medium(row["Medium"].strip()))
                task = MetabolicTask(
                    task_id=task_id,
                    task_type=task_type,
                    target_id=target_id,
                    medium=task_medium,
                    constraints=self._parse_constraints(row["Constraints"].strip()),
                    expected_operator=operator,
                    expected_value=value,
                    description=row["Description"].strip(),
                    category=row["Category"].strip(),
                )
                tasks.append(task)
                seen_task_ids.add(task_id)

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
            match = re.fullmatch(r"(.+?)\(([^)]+)\)", entry)
            if not match:
                raise ValueError(f"Invalid medium entry: {entry}")
            met_id = match.group(1).strip()
            bound = float(match.group(2))
            if not met_id or not math.isfinite(bound):
                raise ValueError(f"Invalid medium entry: {entry}")
            reaction_id = met_id if met_id.startswith("EX_") else f"EX_{met_id}"
            medium[reaction_id] = bound
        return medium

    def _parse_constraints(self, constraint_str: str) -> dict[str, tuple[float, float]]:
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
            match = re.fullmatch(r"(.+?)\(([^#]+)#([^)]+)\)", entry)
            if not match:
                raise ValueError(f"Invalid constraint entry: {entry}")
            rxn_id = match.group(1).strip()
            lower = float(match.group(2))
            upper = float(match.group(3))
            if not rxn_id or not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
                raise ValueError(f"Invalid constraint entry: {entry}")
            constraints[rxn_id] = (lower, upper)
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
        if not math.isfinite(value):
            raise ValueError(f"Expected value must be finite: {expected_str}")
        return operator, value


class TaskRunner:
    """Run metabolic tasks against a COBRA model using FBA."""

    _TOLERANCE = 1e-6

    # Exchange reactions kept open during task simulation.
    # Water and protons are universally present in any aqueous medium
    # and must remain freely exchangeable for FBA feasibility.
    _FREE_EXCHANGE = frozenset({"EX_h2o_e", "EX_h_e"})

    # Validated balanced turnover reactions for nucleotide triphosphates.
    #
    # A simple demand reaction ("met -> nothing") breaks the cofactor
    # recycling loop: e.g. DM_atp_c removes ATP but does not return
    # ADP + Pi, so ATP synthase has no substrate and FBA yields zero.
    #
    # Instead we use the physiological turnover reaction so the
    # recycled partner is returned to the pool and mass balance is
    # maintained.  Stoichiometries follow BiGG conventions.
    _COFACTOR_TURNOVER: dict[str, dict[str, float]] = {
        # NTP hydrolysis: ntp + h2o -> ndp + pi + h
        "atp_c": {"atp_c": -1, "h2o_c": -1, "adp_c": 1, "pi_c": 1, "h_c": 1},
        "gtp_c": {"gtp_c": -1, "h2o_c": -1, "gdp_c": 1, "pi_c": 1, "h_c": 1},
        "ctp_c": {"ctp_c": -1, "h2o_c": -1, "cdp_c": 1, "pi_c": 1, "h_c": 1},
        "utp_c": {"utp_c": -1, "h2o_c": -1, "udp_c": 1, "pi_c": 1, "h_c": 1},
    }

    @staticmethod
    def _normalize_id(raw_id: str) -> str:
        """Convert a model ID to BiGG-standard form for lookup.

        Handles old SBML naming conventions:
          _DASH_  → __     (e.g. glc_DASH_D → glc__D)
          _LPAREN_..._RPAREN_  → removed
          _boundary suffix  → removed
        """
        nid = raw_id
        nid = nid.replace("_DASH_", "__")
        nid = nid.replace("_LPAREN_", "_").replace("_RPAREN_", "")
        if nid.endswith("_boundary"):
            nid = nid[: -len("_boundary")]
        return nid

    @staticmethod
    def _build_id_maps(
        model: cobra.Model,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
        """Build normalised-ID → actual-ID maps for reactions and metabolites.

        Old SBML models may have *two* exchange reactions per metabolite:
        - ``EX_foo_LPAREN_e_RPAREN_``: the real exchange (connects external
          and boundary metabolites)
        - ``EX_foo_e_boundary``: an auto-generated boundary sink

        Both must be opened together for FBA to work.  The ``exchange_groups``
        map records, for each normalised exchange ID, *all* model reaction IDs
        that correspond to it.

        Because the two variants may normalise to *different* keys (e.g.
        ``EX_glc_e`` vs ``EX_glc__D_e``), we also pair them by shared
        boundary metabolite and merge the groups.

        Returns ``(reaction_map, metabolite_map, exchange_groups)``.
        """
        rxn_map: dict[str, str] = {}
        exchange_groups: dict[str, list[str]] = {}

        for rxn in model.reactions:
            rxn_map[rxn.id] = rxn.id  # exact match always available
            norm = TaskRunner._normalize_id(rxn.id)
            if norm == rxn.id:
                continue
            existing = rxn_map.get(norm)
            if (
                existing is None
                or existing.endswith("_boundary")
                and not rxn.id.endswith("_boundary")
            ):
                rxn_map[norm] = rxn.id

            # Collect all actual IDs that normalise to the same exchange ID
            if rxn.id.startswith("EX_"):
                exchange_groups.setdefault(norm, []).append(rxn.id)

        # Pair _LPAREN_ and _boundary exchanges that share a boundary metabolite
        # but normalised to different keys.
        boundary_met_to_rxn: dict[str, str] = {}  # boundary_met_id → boundary EX_ rxn id
        lparen_met_to_key: dict[str, str] = {}  # boundary_met_id → normalised key of _LPAREN_ rxn

        for rxn in model.reactions:
            if not rxn.id.startswith("EX_"):
                continue
            met_ids = {m.id for m in rxn.metabolites}
            b_mets = [m for m in met_ids if m.endswith("_boundary")]
            if rxn.id.endswith("_boundary") and len(met_ids) == 1 and b_mets:
                boundary_met_to_rxn[b_mets[0]] = rxn.id
            elif "LPAREN" in rxn.id and b_mets:
                norm_key = TaskRunner._normalize_id(rxn.id)
                for bm in b_mets:
                    lparen_met_to_key[bm] = norm_key

        # For each boundary metabolite, merge the _boundary rxn into the
        # group that contains the _LPAREN_ rxn (and vice versa).
        for b_met, boundary_rxn in boundary_met_to_rxn.items():
            lparen_key = lparen_met_to_key.get(b_met)
            if not lparen_key:
                continue
            boundary_key = TaskRunner._normalize_id(boundary_rxn)
            if boundary_key == lparen_key:
                continue  # already in same group

            # Merge: ensure both groups have all members
            all_ids = set(exchange_groups.get(lparen_key, []))
            all_ids.update(exchange_groups.get(boundary_key, []))
            all_ids_list = sorted(all_ids)
            exchange_groups[lparen_key] = all_ids_list
            exchange_groups[boundary_key] = all_ids_list

        met_map: dict[str, str] = {}
        for met in model.metabolites:
            met_map[met.id] = met.id
            norm = TaskRunner._normalize_id(met.id)
            if norm == met.id:
                continue
            existing = met_map.get(norm)
            if (
                existing is None
                or existing.endswith("_boundary")
                and not met.id.endswith("_boundary")
            ):
                met_map[norm] = met.id

        return rxn_map, met_map, exchange_groups

    # Compartment suffixes used by some models (e.g. iJO1366 uses "pp"
    # for periplasmic reactions where BiGG standard omits the suffix).
    _COMPARTMENT_SUFFIXES = ("pp", "p", "c", "e", "im")

    def _resolve_reaction(self, rxn_id: str, rxn_map: dict[str, str]) -> str | None:
        """Resolve a BiGG-standard reaction ID to the model's actual ID.

        Falls back to trying common compartment suffixes (e.g. ATPS4r → ATPS4rpp).
        """
        result = rxn_map.get(rxn_id)
        if result is not None:
            return result
        for suffix in self._COMPARTMENT_SUFFIXES:
            result = rxn_map.get(f"{rxn_id}{suffix}")
            if result is not None:
                return result
        return None

    def _resolve_metabolite(self, met_id: str, met_map: dict[str, str]) -> str | None:
        """Resolve a BiGG-standard metabolite ID to the model's actual ID."""
        return met_map.get(met_id)

    def _resolve_exchange_group(
        self, rxn_id: str, exchange_groups: dict[str, list[str]]
    ) -> list[str]:
        """Return all actual exchange IDs that correspond to a BiGG exchange ID.

        For models with dual exchange reactions (``_LPAREN_`` + ``_boundary``),
        this returns both so they can be opened together.
        """
        return exchange_groups.get(rxn_id, [rxn_id])

    def run_task(self, model: cobra.Model, task: MetabolicTask) -> TaskResult:
        """Run a single metabolic task and return the result.

        Steps:
        1. Copy model to avoid side effects
        2. Build ID normalisation maps (handles old SBML naming)
        3. Close all exchange reactions (lower_bound = 0)
        4. Apply medium bounds
        5. Apply additional constraints
        6. Set objective based on task type
        7. Optimize and compare with expected value
        """
        try:
            test_model = self.prepare_task_model(model, task)

            # Optimize
            solution = test_model.optimize()
            logger.debug(
                "Task %s: solver status=%s, objective=%.6g",
                task.task_id,
                solution.status,
                solution.objective_value if solution.objective_value is not None else 0.0,
            )

            if solution.status != "optimal" or solution.objective_value is None:
                status = solution.status or "unknown"
                return TaskResult(
                    task=task,
                    passed=False,
                    actual_value=0.0,
                    error_message=f"Optimization did not produce a valid optimum ({status})",
                    solver_status=status,
                )

            actual = solution.objective_value

            passed = self._check_expected(actual, task.expected_operator, task.expected_value)

            return TaskResult(
                task=task,
                passed=passed,
                actual_value=actual,
                solver_status=solution.status,
            )

        except Exception as exc:
            logger.error("Error running task %s: %s", task.task_id, exc)
            return TaskResult(
                task=task,
                passed=False,
                actual_value=0.0,
                error_message=str(exc),
                solver_status="error",
            )

    def prepare_task_model(
        self,
        model: cobra.Model,
        task: MetabolicTask,
        *,
        copy_model: bool = True,
    ) -> cobra.Model:
        """Prepare a model copy for evaluating or gap-filling one task.

        This is the single source of truth for task medium, extra
        constraints, ID normalisation, and objective construction.  Gap-fill
        must use the same model environment as task evaluation; otherwise it
        can declare a task infeasible even when the full model passes it.
        """
        test_model = model.copy() if copy_model else model
        rxn_map, met_map, exchange_groups = self._build_id_maps(test_model)

        self._apply_task_environment(test_model, task, rxn_map, exchange_groups)
        self._set_task_objective(test_model, task, rxn_map, met_map)
        return test_model

    def _apply_task_environment(
        self,
        model: cobra.Model,
        task: MetabolicTask,
        rxn_map: dict[str, str],
        exchange_groups: dict[str, list[str]],
    ) -> None:
        """Apply the task medium and reaction constraints to ``model``."""
        keep_open: set[str] = set()
        for free_id in self._FREE_EXCHANGE:
            keep_open.update(self._resolve_exchange_group(free_id, exchange_groups))

        default_lb: dict[str, float] = {
            rxn.id: rxn.lower_bound for rxn in model.reactions if rxn.id in keep_open
        }

        closed_count = 0
        for rxn in model.reactions:
            if not rxn.id.startswith("EX_"):
                continue
            if rxn.id.endswith("_boundary"):
                continue
            if rxn.lower_bound < 0:
                rxn.lower_bound = 0.0
                closed_count += 1

        for rxn_id, lb in default_lb.items():
            model.reactions.get_by_id(rxn_id).lower_bound = lb

        logger.debug(
            "Closed %d exchanges, restored %d free exchange(s)",
            closed_count,
            len(default_lb),
        )

        self._apply_medium(model, task.medium, rxn_map, exchange_groups)
        self._apply_constraints(model, task.constraints, rxn_map, exchange_groups)

    def _set_task_objective(
        self,
        model: cobra.Model,
        task: MetabolicTask,
        rxn_map: dict[str, str],
        met_map: dict[str, str],
    ) -> None:
        """Set the objective for a task-prepared model."""
        if task.task_type == "Metabolite":
            actual_met_id = self._resolve_metabolite(task.target_id, met_map)
            if not actual_met_id:
                raise ValueError(f"Metabolite '{task.target_id}' not found in model")

            obj_rxn = self._make_demand_reaction(
                model,
                task.target_id,
                actual_met_id,
                met_map,
            )
            model.add_reactions([obj_rxn])
            model.objective = obj_rxn.id
            return

        if task.task_type == "Reaction":
            actual_rxn_id = self._resolve_reaction(task.target_id, rxn_map)
            if not actual_rxn_id:
                raise ValueError(f"Reaction '{task.target_id}' not found in model")
            model.objective = actual_rxn_id
            return

        raise ValueError(f"Unknown task type: {task.task_type}")

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

    @staticmethod
    def _unique_objective_reaction_id(model: cobra.Model, base_id: str) -> str:
        """Return a reaction ID not already used in ``model``.

        The task objective reaction must be added fresh: cobra silently ignores
        ``add_reactions`` for a duplicate ID, so a base ID that collides with a
        pre-existing reaction (e.g. the model's own ``DM_atp_c``) would bind the
        objective to that reaction's bounds/stoichiometry and yield a wrong
        task verdict.
        """
        if base_id not in model.reactions:
            return base_id
        candidate = f"{base_id}_taskobj"
        i = 1
        while candidate in model.reactions:
            i += 1
            candidate = f"{base_id}_taskobj{i}"
        return candidate

    def _make_demand_reaction(
        self,
        model: cobra.Model,
        target_id: str,
        actual_met_id: str,
        met_map: dict[str, str],
    ) -> cobra.Reaction:
        """Create a demand/turnover reaction for a metabolite objective.

        For cycling cofactors (ATP, NADH, etc.) a balanced turnover
        reaction is used so that the recycled partner (ADP, NAD+, …)
        is returned to the pool.  This prevents the FBA steady-state
        constraint from starving the production pathway of substrates.

        For non-cycling metabolites a simple demand ``met ->`` is used.
        """
        turnover = self._COFACTOR_TURNOVER.get(target_id)

        if turnover is not None:
            # Check that ALL participants exist in the model.
            stoich: dict[cobra.Metabolite, float] = {}
            all_present = True
            for met_id, coeff in turnover.items():
                resolved = met_map.get(met_id)
                if resolved is None:
                    all_present = False
                    break
                try:
                    stoich[model.metabolites.get_by_id(resolved)] = coeff
                except KeyError:
                    all_present = False
                    break

            if all_present and stoich:
                rxn = cobra.Reaction(
                    self._unique_objective_reaction_id(model, f"TURNOVER_{actual_met_id}")
                )
                rxn.add_metabolites(stoich)
                rxn.lower_bound = 0.0
                rxn.upper_bound = 1000.0
                logger.debug(
                    "Using balanced turnover for %s: %s",
                    target_id,
                    rxn.reaction if hasattr(rxn, "reaction") else stoich,
                )
                return rxn

            logger.debug(
                "Turnover partners missing for %s, falling back to simple demand",
                target_id,
            )

        # Fallback: simple demand reaction
        met = model.metabolites.get_by_id(actual_met_id)
        rxn = cobra.Reaction(self._unique_objective_reaction_id(model, f"DM_{actual_met_id}"))
        rxn.add_metabolites({met: -1.0})
        rxn.lower_bound = 0.0
        rxn.upper_bound = 1000.0
        return rxn

    def _apply_medium(
        self,
        model: cobra.Model,
        medium: dict[str, float],
        rxn_map: dict[str, str],
        exchange_groups: dict[str, list[str]],
    ) -> None:
        """Set exchange reaction bounds according to medium specification.

        Opens *all* exchange reactions in the group (e.g. both ``_LPAREN_``
        and ``_boundary`` variants) so that old SBML models work correctly.
        """
        applied = 0
        for rxn_id, lower_bound in medium.items():
            group = exchange_groups.get(rxn_id, [])
            if not group:
                actual_id = self._resolve_reaction(rxn_id, rxn_map)
                group = [actual_id] if actual_id else []
            for actual_id in group:
                try:
                    rxn = model.reactions.get_by_id(actual_id)
                    rxn.lower_bound = lower_bound
                    applied += 1
                except KeyError:
                    logger.warning(
                        "Exchange reaction '%s' (group member '%s') not found",
                        rxn_id,
                        actual_id,
                    )
            if not group:
                logger.warning("Exchange '%s' could not be resolved", rxn_id)
        logger.debug("Applied medium: %d reactions set", applied)

    def _apply_constraints(
        self,
        model: cobra.Model,
        constraints: dict[str, tuple[float, float]],
        rxn_map: dict[str, str],
        exchange_groups: dict[str, list[str]],
    ) -> None:
        """Apply additional bound constraints to reactions.

        For exchange reactions, applies to all members of the exchange group.
        """
        for rxn_id, (lower, upper) in constraints.items():
            if rxn_id.startswith("EX_"):
                group = exchange_groups.get(rxn_id, [])
                if not group:
                    actual_id = self._resolve_reaction(rxn_id, rxn_map)
                    group = [actual_id] if actual_id else []
                for actual_id in group:
                    try:
                        rxn = model.reactions.get_by_id(actual_id)
                        rxn.lower_bound = lower
                        rxn.upper_bound = upper
                    except KeyError:
                        logger.warning(
                            "Reaction '%s' (group member '%s') not found for constraint",
                            rxn_id,
                            actual_id,
                        )
                if not group:
                    logger.warning("Reaction '%s' could not be resolved for constraint", rxn_id)
            else:
                actual_id = self._resolve_reaction(rxn_id, rxn_map)
                if actual_id:
                    try:
                        rxn = model.reactions.get_by_id(actual_id)
                        rxn.lower_bound = lower
                        rxn.upper_bound = upper
                    except KeyError:
                        logger.warning("Reaction '%s' (resolved '%s') not found", rxn_id, actual_id)
                else:
                    logger.warning("Reaction '%s' could not be resolved", rxn_id)

    def _check_expected(self, actual: float, operator: str, expected: float) -> bool:
        """Check whether actual value satisfies the expected condition.

        Operators: >, <, =, >=, <=
        Uses tolerance of 1e-6 for floating-point comparison.

        For strict inequalities (> and <), tolerance makes the check
        stricter: actual must be clearly above/below the expected value
        to avoid false positives from floating-point noise.
        """
        tol = self._TOLERANCE
        if operator == ">":
            return actual > expected + tol
        elif operator == "<":
            return actual < expected - tol
        elif operator == "=":
            return abs(actual - expected) < tol
        elif operator == ">=":
            return actual >= expected - tol
        elif operator == "<=":
            return actual <= expected + tol
        else:
            logger.warning("Unknown operator: %s", operator)
            return False
