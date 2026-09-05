"""Gap-filling engine orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

import cobra
from cobra.exceptions import OptimizationError

from src.cache.cache_manager import CacheManager
from src.core.cobra_utils import convert_cobra_reaction
from src.core.gpr_parser import extract_genes, parse_gpr
from src.core.mapping_data import MappingData
from src.core.models import (
    CandidateReaction,
    GapFillResult,
    MetabolicTask,
    ReactionEvidence,
    TaskResult,
)
from src.core.task_parser import TaskRunner
from src.core.universal_loader import UniversalLoader
from src.gapfill.gpr_assigner import GPRAssigner
from src.gapfill.organism_filter import OrganismFilter
from src.gapfill.penalty_calculator import PenaltyCalculator
from src.utils.config import Config

logger = logging.getLogger("metataskgapfill.gapfill.engine")


class _CancelEvent(Protocol):
    """Minimal cancellation event contract used by GUI/async workers."""

    def is_set(self) -> bool: ...


class GapFillEngine:
    """Task-driven gap-filling orchestrator.

    Runs a 5-phase pipeline:
    1. testing_before: Run all tasks on current model
    2. filtering: OrganismFilter.filter_candidates()
    3. gap_filling: COBRApy gap-fill per failed task
    4. assigning_gpr: GPRAssigner.assign_batch()
    5. testing_after: Run all tasks on improved model
    """

    def __init__(self, config: Config, *, evidence_weighted: bool = True) -> None:
        self._config = config
        self._evidence_weighted = evidence_weighted
        self._task_runner = TaskRunner()
        self._penalty_calc = PenaltyCalculator(config)
        self._gpr_assigner: GPRAssigner | None = None
        self._organism_filter: OrganismFilter | None = None

    async def initialize(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
        mapping_data: MappingData | None = None,
    ) -> None:
        """Initialize organism filter and GPR assigner."""
        if self._evidence_weighted:
            self._organism_filter = OrganismFilter(
                organism_code=organism_code,
                cache_manager=cache_manager,
                mapping_data=mapping_data,
            )
            await self._organism_filter.initialize()

        self._gpr_assigner = GPRAssigner(
            organism_code=organism_code,
            cache_manager=cache_manager,
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self._organism_filter:
            await self._organism_filter.close()
            self._organism_filter = None
        if self._gpr_assigner:
            await self._gpr_assigner.close()
            self._gpr_assigner = None

    async def run(
        self,
        user_model: cobra.Model,
        universal_model: cobra.Model,
        candidates: list[CandidateReaction],
        tasks: list[MetabolicTask],
        evidence_results: dict[str, ReactionEvidence],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        cancel_event: _CancelEvent | None = None,
        start_phase: int = 1,
        preloaded_result: GapFillResult | None = None,
    ) -> GapFillResult:
        """Execute the full gap-filling pipeline.

        Args:
            user_model: The user's cobra Model (will be modified in place).
            universal_model: The universal cobra Model for gap-filling.
            candidates: Candidate reactions extracted from universal model.
            tasks: Metabolic tasks for testing.
            evidence_results: Evidence scores for candidates.
            progress_callback: Optional (phase, current, total, detail) callback.
            cancel_event: Optional event to signal cancellation.
            start_phase: Phase to start from (1-5), for resume support.
            preloaded_result: Complete runtime checkpoint for resume.

        Returns:
            GapFillResult with before/after task results and added reactions.

        With ``evidence_weighted=False``, every candidate costs 1 regardless of
        evidence or organism annotations. GPR assignment happens after selection.
        """
        result = preloaded_result or GapFillResult()
        result.total_tasks = len(tasks)
        result.is_partial = False
        result.all_candidates = list(candidates)
        result.evidence_results = dict(evidence_results)

        def _progress(phase: str, current: int, total: int, detail: str) -> None:
            if progress_callback:
                progress_callback(phase, current, total, detail)

        def _is_cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        # Phase 1: Initial task testing
        if start_phase <= 1:
            _progress("testing_before", 0, len(tasks), "Running initial tests...")
            result.task_results_before = self._run_tasks(
                user_model,
                tasks,
                phase="before",
                progress_callback=lambda c, t, d: _progress("testing_before", c, t, d),
            )
            result.completed_phase = 1

            if _is_cancelled():
                result.is_partial = True
                return result
        elif not result.task_results_before:
            raise ValueError("Cannot resume after Phase 1 without initial task results")
        else:
            result.completed_phase = 1

        failed_tasks = [r.task for r in result.task_results_before if not r.passed]
        logger.info(
            "Phase 1 complete: %d/%d tasks passed, %d failed",
            len(tasks) - len(failed_tasks),
            len(tasks),
            len(failed_tasks),
        )

        if not failed_tasks:
            logger.info("All tasks pass — no gap-filling needed")
            # Re-run tasks tagged as "after" for consistency
            _progress("testing_after", 0, len(tasks), "Running final tests...")
            result.task_results_after = self._run_tasks(
                user_model,
                tasks,
                phase="after",
                progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
            )
            result.completed_phase = 5
            return result

        # Phase 2: Organism filtering
        if start_phase <= 2:
            if self._evidence_weighted and self._organism_filter:
                _progress("filtering", 0, len(candidates), "Filtering by organism...")
                await self._organism_filter.filter_candidates(
                    candidates,
                    progress_callback=lambda c, t, d: _progress("filtering", c, t, d),
                )
                logger.info("Phase 2 complete: organism filtering done")

            # Calculate penalties
            penalties = (
                self._penalty_calc.calculate_batch(candidates, evidence_results)
                if self._evidence_weighted
                else {candidate.reaction.id: 1.0 for candidate in candidates}
            )
            # Update candidate penalties
            for candidate in candidates:
                if candidate.reaction.id in penalties:
                    candidate.penalty = penalties[candidate.reaction.id]
                ev = evidence_results.get(candidate.reaction.id)
                if not self._evidence_weighted:
                    candidate.evidence_tier = None
                elif ev is not None:
                    candidate.evidence_tier = ev.evidence_tier

            result.all_candidates = list(candidates)
            result.completed_phase = 2

            if _is_cancelled():
                result.is_partial = True
                return result
        else:
            # Still need penalties for Phase 3
            penalties = (
                self._penalty_calc.calculate_batch(candidates, evidence_results)
                if self._evidence_weighted
                else {candidate.reaction.id: 1.0 for candidate in candidates}
            )
            for candidate in candidates:
                if candidate.reaction.id in penalties:
                    candidate.penalty = penalties[candidate.reaction.id]
                ev = evidence_results.get(candidate.reaction.id)
                if not self._evidence_weighted:
                    candidate.evidence_tier = None
                elif ev is not None:
                    candidate.evidence_tier = ev.evidence_tier

        latest_after_results: list[TaskResult] | None = None
        gapfill_universal = self._exclude_exchange_reactions_from_universal(
            universal_model,
            tasks,
        )
        gapfill_universal = self._prune_universal_for_gapfill(
            gapfill_universal,
            user_model,
            tasks,
        )
        if gapfill_universal is not universal_model:
            _progress(
                "gap_filling",
                0,
                1,
                (
                    f"Pruned universal model for gap-fill: "
                    f"{len(gapfill_universal.reactions)}/{len(universal_model.reactions)} reactions"
                ),
            )

        # Phase 3: Gap-filling
        if start_phase <= 3:
            pre_phase3_reaction_ids = self._model_reaction_ids(user_model)
            current_results = result.task_results_before
            added_by_id: dict[str, CandidateReaction] = {}
            max_iterations = max(1, self._config.gapfill_iterations)
            prev_passed = sum(1 for r in current_results if r.passed)
            protected_task_ids = {r.task.task_id for r in current_results if r.passed}
            protected_tasks = [r.task for r in current_results if r.passed]

            for iteration in range(max_iterations):
                failed_tasks = [r.task for r in current_results if not r.passed]
                gapfillable_tasks = [t for t in failed_tasks if self._is_gapfillable_task(t)]
                skipped_tasks = [t for t in failed_tasks if not self._is_gapfillable_task(t)]

                if skipped_tasks:
                    logger.info(
                        "Skipping %d non-gap-fillable failed tasks: %s",
                        len(skipped_tasks),
                        ", ".join(t.task_id for t in skipped_tasks),
                    )

                if not gapfillable_tasks:
                    logger.info("No gap-fillable failed tasks remain")
                    break

                _progress(
                    "gap_filling",
                    iteration,
                    max_iterations,
                    f"Iteration {iteration + 1}: {len(gapfillable_tasks)} failed task(s)",
                )
                added_reactions = await self._run_gapfill(
                    user_model,
                    gapfill_universal,
                    gapfillable_tasks,
                    penalties,
                    result,
                    progress_callback=lambda c, t, d: _progress("gap_filling", c, t, d),
                    cancel_event=cancel_event,
                    protected_tasks=protected_tasks,
                )

                if not added_reactions:
                    logger.info("Gap-fill iteration %d added no reactions", iteration + 1)
                    break

                existing_before = self._model_reaction_ids(user_model)
                added_candidates = self._apply_gapfill_results(
                    user_model, added_reactions, candidates
                )
                iteration_new_ids: list[str] = []
                newly_added = 0
                for candidate in added_candidates:
                    reaction_id = candidate.reaction.id
                    if reaction_id not in added_by_id:
                        added_by_id[reaction_id] = candidate
                        newly_added += 1
                        if reaction_id not in existing_before:
                            iteration_new_ids.append(reaction_id)

                if newly_added == 0:
                    logger.info("Gap-fill iteration %d produced no new reactions", iteration + 1)
                    break

                current_results = self._run_tasks(
                    user_model,
                    tasks,
                    phase="after",
                    progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
                )
                latest_after_results = current_results
                passed_now = sum(1 for r in current_results if r.passed)
                protected_regressions = self._regressed_protected_tasks(
                    current_results,
                    protected_task_ids,
                )

                if protected_regressions:
                    logger.info(
                        "Gap-fill iteration %d regressed protected task(s) %s; "
                        "rolling back %d reaction(s) and stopping",
                        iteration + 1,
                        ", ".join(sorted(protected_regressions)),
                        len(iteration_new_ids),
                    )
                    self._rollback_gapfill_results(
                        user_model,
                        added_candidates,
                        iteration_new_ids,
                        added_by_id,
                    )
                    current_results = self._run_tasks(
                        user_model,
                        tasks,
                        phase="after",
                        progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
                    )
                    latest_after_results = current_results
                    break

                if all(r.passed for r in current_results):
                    logger.info("All tasks pass after gap-fill iteration %d", iteration + 1)
                    break

                # Stop if an iteration produced no net improvement in passing
                # tasks — added reactions that fix nothing (or break as many as
                # they fix) should not keep accumulating across iterations.
                if passed_now <= prev_passed:
                    logger.info(
                        "Gap-fill iteration %d fixed no additional tasks "
                        "(%d -> %d passing); rolling back %d reaction(s) and stopping",
                        iteration + 1,
                        prev_passed,
                        passed_now,
                        len(iteration_new_ids),
                    )
                    self._rollback_gapfill_results(
                        user_model,
                        added_candidates,
                        iteration_new_ids,
                        added_by_id,
                    )
                    current_results = self._run_tasks(
                        user_model,
                        tasks,
                        phase="after",
                        progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
                    )
                    latest_after_results = current_results
                    break
                prev_passed = passed_now

                if _is_cancelled():
                    result.is_partial = True
                    break

            result.added_reactions = list(added_by_id.values())
            result.added_reactions.sort(
                key=lambda c: (
                    (
                        evidence_results[c.reaction.id].evidence_tier.rank,
                        evidence_results[c.reaction.id].confidence_score,
                    )
                    if c.reaction.id in evidence_results
                    else (0, 0.0)
                ),
                reverse=True,
            )
            logger.info(
                "Phase 3 complete: %d reactions added to model in %d iteration(s)",
                len(result.added_reactions),
                result.iterations,
            )

            result.completed_phase = 3

            if _is_cancelled():
                phase3_added_ids = sorted(
                    self._model_reaction_ids(user_model) - pre_phase3_reaction_ids
                )
                if phase3_added_ids:
                    user_model.remove_reactions(phase3_added_ids, remove_orphans=False)
                result.added_reactions = []
                result.task_results_after = []
                result.iterations = 0
                result.completed_phase = 2
                result.is_partial = True
                return result

        # Phase 4: GPR assignment
        if start_phase <= 4:
            if self._gpr_assigner and result.added_reactions:
                _progress("assigning_gpr", 0, len(result.added_reactions), "Assigning GPR...")
                await self._gpr_assigner.assign_batch(
                    result.added_reactions,
                    progress_callback=lambda c, t, d: _progress("assigning_gpr", c, t, d),
                    allowed_gene_ids=self._model_gene_ids(user_model),
                    evidence_results=evidence_results,
                )
                if _is_cancelled():
                    result.completed_phase = 3
                    result.is_partial = True
                    return result
                self._apply_assigned_gprs(user_model, result.added_reactions)
                logger.info("Phase 4 complete: GPR assignment done")

            result.completed_phase = 4

            if _is_cancelled():
                result.is_partial = True
                return result

        # Phase 5: Final task testing
        if latest_after_results is None:
            _progress("testing_after", 0, len(tasks), "Running final tests...")
            result.task_results_after = self._run_tasks(
                user_model,
                tasks,
                phase="after",
                progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
            )
        else:
            result.task_results_after = latest_after_results
            _progress("testing_after", len(tasks), len(tasks), "Final tests complete")

        # Calculate tasks fixed and tasks broken (regressions)
        before_failed = {r.task.task_id for r in result.task_results_before if not r.passed}
        before_passed = {r.task.task_id for r in result.task_results_before if r.passed}
        after_passed = {r.task.task_id for r in result.task_results_after if r.passed}
        after_failed = {r.task.task_id for r in result.task_results_after if not r.passed}
        result.tasks_fixed = len(before_failed & after_passed)
        result.tasks_broken = len(before_passed & after_failed)

        if result.tasks_broken:
            logger.warning(
                "Gap-fill regressed %d previously-passing task(s): %s",
                result.tasks_broken,
                ", ".join(sorted(before_passed & after_failed)),
            )
        result.completed_phase = 5

        logger.info(
            "Phase 5 complete: %d/%d tasks now pass (%d fixed)",
            sum(1 for r in result.task_results_after if r.passed),
            len(tasks),
            result.tasks_fixed,
        )

        return result

    @staticmethod
    def _model_gene_ids(model: cobra.Model) -> set[str]:
        """Return genes already supported by the draft model/proteome."""
        try:
            return set(model.genes.list_attr("id"))
        except Exception:
            return set()

    @staticmethod
    def _apply_assigned_gprs(
        model: cobra.Model,
        candidates: list[CandidateReaction],
    ) -> None:
        """Persist supported GPR assignments in COBRA and domain reactions."""
        for candidate in candidates:
            if not candidate.assigned_gpr:
                continue
            try:
                cobra_reaction = model.reactions.get_by_id(candidate.reaction.id)
            except (AttributeError, KeyError):
                logger.warning(
                    "Cannot apply assigned GPR: reaction %s is not in the model",
                    candidate.reaction.id,
                )
                continue
            cobra_reaction.gene_reaction_rule = candidate.assigned_gpr
            candidate.reaction.gene_reaction_rule = candidate.assigned_gpr
            candidate.reaction.genes = extract_genes(candidate.assigned_gpr)
            candidate.reaction.gpr_tree = parse_gpr(candidate.assigned_gpr)

    def _run_tasks(
        self,
        model: cobra.Model,
        tasks: list[MetabolicTask],
        phase: str = "before",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[TaskResult]:
        """Run all metabolic tasks and tag results with phase."""
        results = self._task_runner.run_all(model, tasks, progress_callback=progress_callback)
        for r in results:
            r.phase = phase
        return results

    async def _run_gapfill(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        failed_tasks: list[MetabolicTask],
        penalties: dict[str, float],
        result: GapFillResult,
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: _CancelEvent | None = None,
        protected_tasks: list[MetabolicTask] | None = None,
    ) -> list[cobra.Reaction]:
        """Run task-driven gap-filling for each failed task.

        For each failed task:
        1. Copy model
        2. Apply task medium/constraints
        3. Set task target as objective
        4. Run cobra.flux_analysis.gapfill()
        5. Collect added reactions (deduplicate)

        If infeasible, retry with lower_bound=0.01, then record as infeasible.
        """
        all_added: dict[str, cobra.Reaction] = {}  # deduplicate by ID

        for i, task in enumerate(failed_tasks):
            # Check cancel between tasks
            if cancel_event is not None and cancel_event.is_set():
                logger.info("Gap-fill cancelled at task %d/%d", i, len(failed_tasks))
                break

            if progress_callback:
                progress_callback(i + 1, len(failed_tasks), f"Gap-filling for task {task.task_id}")

            required = self._lower_bound_for_task(task)
            try:
                solution_sets = self._gapfill_solutions_for_task(
                    model,
                    universal,
                    task,
                    penalties,
                    required,
                    alternatives=max(1, self._config.gapfill_alternatives),
                )
            except (RuntimeError, OptimizationError):
                # Solver infeasibility near the requested bound: retry at a
                # relaxed bound, but only keep reactions that genuinely satisfy
                # the task's real threshold (see _retry_gapfill). cobra raises
                # OptimizationError/Infeasible (NOT a RuntimeError subclass) when
                # the MILP is infeasible, so both must be caught here.
                solution_sets = self._retry_gapfill(
                    model, universal, task, penalties, required, result
                )
            except Exception as e:
                logger.warning("Gap-fill failed for task %s: %s", task.task_id, e)
                self._mark_infeasible(result, task)
                continue

            if not solution_sets:
                self._mark_infeasible(result, task)
                continue

            accepted: list[cobra.Reaction] | None = None
            for alt_idx, reactions in enumerate(solution_sets, start=1):
                proposed = list(all_added.values())
                proposed.extend(r for r in reactions if r.id not in all_added)
                if (
                    proposed
                    and protected_tasks
                    and not self._reactions_preserve_tasks(
                        model,
                        universal,
                        protected_tasks,
                        proposed,
                    )
                ):
                    logger.info(
                        "Gap-fill solution %d for task %s would regress an "
                        "already passing task; trying next alternative",
                        alt_idx,
                        task.task_id,
                    )
                    continue
                accepted = reactions
                break

            if accepted is None:
                logger.info(
                    "No gap-fill alternative for task %s preserves protected tasks",
                    task.task_id,
                )
                self._mark_infeasible(result, task)
                continue

            for rxn in accepted:
                if rxn.id not in all_added:
                    all_added[rxn.id] = rxn

        if progress_callback:
            progress_callback(len(failed_tasks), len(failed_tasks), "Gap-fill complete")

        result.iterations += 1
        return list(all_added.values())

    # Relaxation factor for the solver-infeasibility retry.  The retry exists
    # only to dodge numerical infeasibility near the requested bound — it must
    # not silently accept a solution far below the task's real requirement.
    _RETRY_RELAX_FACTOR = 0.5
    _RETRY_MIN_BOUND = 0.01

    def _retry_gapfill(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        task: MetabolicTask,
        penalties: dict[str, float],
        required: float,
        result: GapFillResult,
    ) -> list[list[cobra.Reaction]]:
        """Retry gap-fill at a relaxed bound after a solver infeasibility.

        The relaxed bound scales with the task requirement so a high-threshold
        task (e.g. ``>=10``) is never "solved" by a near-zero flux.  Any
        reactions found at the relaxed bound are kept only if they actually let
        the task pass at its real threshold; otherwise they are discarded so we
        never inject spurious reactions that leave the task failing.
        """
        retry_bound = max(self._RETRY_MIN_BOUND, required * self._RETRY_RELAX_FACTOR)
        if retry_bound >= required:
            # Nothing meaningful to relax (requirement already at/below floor).
            self._mark_infeasible(result, task)
            return []

        try:
            solution_sets = self._gapfill_solutions_for_task(
                model,
                universal,
                task,
                penalties,
                retry_bound,
                alternatives=max(1, self._config.gapfill_alternatives),
            )
        except Exception as e:
            logger.warning("Task %s infeasible: %s", task.task_id, e)
            self._mark_infeasible(result, task)
            return []

        valid_sets = [
            reactions
            for reactions in solution_sets
            if self._reactions_satisfy_task(model, universal, task, reactions)
        ]
        if not valid_sets:
            logger.info(
                "Task %s only reached relaxed bound %.4g (< required %.4g); "
                "discarding spurious alternative solution(s)",
                task.task_id,
                retry_bound,
                required,
            )
            self._mark_infeasible(result, task)
        return valid_sets

    @staticmethod
    def _mark_infeasible(result: GapFillResult, task: MetabolicTask) -> None:
        """Record a task as infeasible once."""
        if task.task_id not in result.infeasible_tasks:
            result.infeasible_tasks.append(task.task_id)

    def _reactions_satisfy_task(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        task: MetabolicTask,
        reactions: list[cobra.Reaction],
    ) -> bool:
        """Return True if adding ``reactions`` lets ``task`` pass its real check.

        Rebuilds the same task environment as evaluation (medium, trace
        elements, cofactor turnover) so the verdict matches the Phase 5
        re-evaluation rather than the relaxed gap-fill bound.
        """
        try:
            test_model = model.copy()
            self._preseed_missing_task_target(test_model, universal, task)
            existing = set(test_model.reactions.list_attr("id"))
            to_add = [r.copy() for r in reactions if r.id not in existing]
            if to_add:
                test_model.add_reactions(to_add)
            test_model = self._task_runner.prepare_task_model(test_model, task, copy_model=False)
            solution = test_model.optimize()
            actual = (
                solution.objective_value
                if solution.status != "infeasible" and solution.objective_value is not None
                else 0.0
            )
        except Exception as e:
            logger.debug("Validation solve failed for %s: %s", task.task_id, e)
            return False

        return self._task_runner._check_expected(
            actual, task.expected_operator, task.expected_value
        )

    def _reactions_preserve_tasks(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        protected_tasks: list[MetabolicTask],
        reactions: list[cobra.Reaction],
    ) -> bool:
        """Return True if adding ``reactions`` keeps protected tasks passing."""
        if not protected_tasks:
            return True

        try:
            test_model = model.copy()
            for task in protected_tasks:
                self._preseed_missing_task_target(test_model, universal, task)
            existing = set(test_model.reactions.list_attr("id"))
            to_add = [r.copy() for r in reactions if r.id not in existing]
            if to_add:
                test_model.add_reactions(to_add)
        except Exception as e:
            logger.debug("Protected-task validation setup failed: %s", e)
            return False

        for task in protected_tasks:
            try:
                check = self._task_runner.run_task(test_model, task)
            except Exception as e:
                logger.debug(
                    "Protected-task validation failed for %s: %s",
                    task.task_id,
                    e,
                )
                return False
            if not check.passed:
                logger.debug(
                    "Protected task %s would regress after gap-fill additions",
                    task.task_id,
                )
                return False
        return True

    @staticmethod
    def _regressed_protected_tasks(
        results: list[TaskResult],
        protected_task_ids: set[str],
    ) -> set[str]:
        """Return protected task IDs that are no longer passing."""
        return {
            result.task.task_id
            for result in results
            if result.task.task_id in protected_task_ids and not result.passed
        }

    def _is_gapfillable_task(self, task: MetabolicTask) -> bool:
        """Return True if adding reactions can plausibly fix ``task``."""
        return task.expected_operator in {">", ">="}

    def _lower_bound_for_task(self, task: MetabolicTask) -> float:
        """Minimum objective value required from COBRApy gap-fill."""
        configured = self._config.gapfill_lower_bound
        if task.expected_operator == ">":
            return max(configured, task.expected_value + (TaskRunner._TOLERANCE * 2.0))
        if task.expected_operator == ">=":
            return max(configured, task.expected_value)
        return configured

    @staticmethod
    def _model_reaction_ids(model: cobra.Model) -> set[str]:
        """Return reaction IDs currently present in ``model``."""
        try:
            return set(model.reactions.list_attr("id"))
        except Exception:
            return set()

    def _gapfill_for_task(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        task: MetabolicTask,
        penalties: dict[str, float],
        lower_bound: float,
    ) -> list[cobra.Reaction]:
        """Run gap-fill for a single task.

        Returns list of reactions that need to be added.
        """
        solutions = self._gapfill_solutions_for_task(
            model,
            universal,
            task,
            penalties,
            lower_bound,
            alternatives=1,
        )
        return solutions[0] if solutions else []

    def _gapfill_solutions_for_task(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        task: MetabolicTask,
        penalties: dict[str, float],
        lower_bound: float,
        alternatives: int = 1,
    ) -> list[list[cobra.Reaction]]:
        """Run gap-fill for a task and return alternative reaction sets."""
        test_model = model.copy()
        # Keep permanent additions separate from the task-local bounds applied
        # to the temporary target reaction in test_model.
        preseeded = [
            reaction.copy()
            for reaction in self._preseed_missing_task_target(test_model, universal, task)
        ]
        solver_universal = universal.copy()
        try:
            test_model = self._task_runner.prepare_task_model(test_model, task, copy_model=False)
            # Candidates absent from the draft still have to obey this task's
            # bounds and medium. Apply only the environment, without adding any
            # objective, demand, or turnover reactions to the universal.
            reaction_map, _, exchange_groups = self._task_runner._build_id_maps(
                test_model, additional_model=solver_universal
            )
            self._task_runner._apply_task_environment(
                solver_universal, task, reaction_map, exchange_groups
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        result = cobra.flux_analysis.gapfilling.gapfill(
            test_model,
            solver_universal,
            lower_bound=lower_bound,
            penalties=penalties,
            demand_reactions=False,
            iterations=max(1, alternatives),
        )

        if not result:
            return [preseeded] if preseeded else []

        solutions: list[list[cobra.Reaction]] = []
        for solution in result:
            reactions_by_id = {rxn.id: rxn for rxn in preseeded}
            for rxn in solution:
                if rxn.id not in reactions_by_id:
                    reactions_by_id[rxn.id] = universal.reactions.get_by_id(rxn.id).copy()
            reactions = list(reactions_by_id.values())
            if reactions:
                solutions.append(reactions)
        return solutions

    def _preseed_missing_task_target(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        task: MetabolicTask,
    ) -> list[cobra.Reaction]:
        """Add a missing task target from universal so it can be optimized.

        COBRApy's gapfill requires the objective to exist in the draft model.
        If a reaction-task target was one of the removed reactions, we add a
        temporary copy before solving and return it as a required gap-fill
        reaction.  For metabolite tasks, a missing target metabolite is added
        if present in the universal model so demand/turnover construction can
        still drive gap-fill.
        """
        if task.task_type == "Reaction":
            model_rxn_map, _, _ = self._task_runner._build_id_maps(model)
            if self._task_runner._resolve_reaction(task.target_id, model_rxn_map):
                return []

            universal_rxn_map, _, _ = self._task_runner._build_id_maps(universal)
            universal_rxn_id = self._task_runner._resolve_reaction(
                task.target_id, universal_rxn_map
            )
            if not universal_rxn_id:
                raise RuntimeError(f"Reaction '{task.target_id}' not found in model or universal")

            rxn = universal.reactions.get_by_id(universal_rxn_id).copy()
            model.add_reactions([rxn])
            return [rxn]

        if task.task_type == "Metabolite":
            _, model_met_map, _ = self._task_runner._build_id_maps(model)
            if self._task_runner._resolve_metabolite(task.target_id, model_met_map):
                return []

            _, universal_met_map, _ = self._task_runner._build_id_maps(universal)
            universal_met_id = self._task_runner._resolve_metabolite(
                task.target_id, universal_met_map
            )
            if not universal_met_id:
                raise RuntimeError(f"Metabolite '{task.target_id}' not found in model or universal")

            model.add_metabolites([universal.metabolites.get_by_id(universal_met_id).copy()])
            return []

        raise RuntimeError(f"Unknown task type: {task.task_type}")

    def _prune_universal_for_gapfill(
        self,
        universal: cobra.Model,
        user_model: cobra.Model,
        tasks: list[MetabolicTask],
    ) -> cobra.Model:
        """Return a smaller universal model for large gap-fill problems.

        BiGG universal JSON can contain tens of thousands of reactions. For
        task-based repair of a draft model, reactions whose metabolites are
        completely outside the draft model usually inflate the MILP without
        helping restore removed reactions. Keep reactions compatible with the
        current model metabolite set, while preserving explicit task targets.
        """
        if not self._config.gapfill_prune_to_model_metabolites:
            return universal

        threshold = max(0, self._config.gapfill_universal_prune_threshold)
        if threshold == 0 or len(universal.reactions) <= threshold:
            return universal

        try:
            allowed_metabolites = set(user_model.metabolites.list_attr("id"))
        except Exception:
            return universal

        if not allowed_metabolites:
            return universal

        # Prune only for MILP size. Directly model-compatible reactions are kept,
        # as are directionally reachable universal paths leading to task targets.
        # The latter is essential: requiring every reaction metabolite to exist in
        # the draft deletes valid A -> B -> C repairs whenever B is a new
        # intermediate. KEGG evidence is never used as a hard filter.
        direct_compatible: set[str] = set()
        target_reaction_ids: set[str] = set()
        target_metabolite_ids: set[str] = set()
        universal_rxn_map, universal_met_map, _ = self._task_runner._build_id_maps(universal)
        for task in tasks:
            if task.task_type == "Reaction":
                rxn_id = self._task_runner._resolve_reaction(task.target_id, universal_rxn_map)
                if rxn_id:
                    target_reaction_ids.add(rxn_id)
                    target_rxn = universal.reactions.get_by_id(rxn_id)
                    target_metabolite_ids.update(met.id for met in target_rxn.metabolites)
            elif task.task_type == "Metabolite":
                met_id = self._task_runner._resolve_metabolite(task.target_id, universal_met_map)
                if met_id:
                    target_metabolite_ids.add(met_id)

        for rxn in universal.reactions:
            metabolite_ids = {met.id for met in rxn.metabolites}
            if metabolite_ids and metabolite_ids <= allowed_metabolites:
                direct_compatible.add(rxn.id)

        forward_reactions = self._forward_reachable_reactions(
            universal,
            allowed_metabolites | target_metabolite_ids,
        )
        backward_reactions = self._backward_relevant_reactions(
            universal,
            target_metabolite_ids,
        )
        path_reactions = forward_reactions & backward_reactions
        keep_reaction_ids = direct_compatible | path_reactions | target_reaction_ids

        if not keep_reaction_ids or len(keep_reaction_ids) >= len(universal.reactions):
            return universal

        pruned = cobra.Model(f"{universal.id}_pruned")
        pruned.name = f"{universal.name or universal.id} (pruned)"
        pruned.compartments = dict(universal.compartments)
        pruned.add_reactions(
            [rxn.copy() for rxn in universal.reactions if rxn.id in keep_reaction_ids]
        )
        logger.info(
            "Pruned universal model for gap-fill from %d to %d reactions",
            len(universal.reactions),
            len(pruned.reactions),
        )
        return pruned

    @staticmethod
    def _reaction_directions(
        reaction: cobra.Reaction,
    ) -> list[tuple[frozenset[str], frozenset[str]]]:
        """Return feasible (required, produced) metabolite sets for a reaction."""
        reactants = frozenset(
            met.id for met, coefficient in reaction.metabolites.items() if coefficient < 0
        )
        products = frozenset(
            met.id for met, coefficient in reaction.metabolites.items() if coefficient > 0
        )
        directions: list[tuple[frozenset[str], frozenset[str]]] = []
        if reaction.upper_bound > 0 and reactants and products:
            directions.append((reactants, products))
        if reaction.lower_bound < 0 and reactants and products:
            directions.append((products, reactants))
        return directions

    def _forward_reachable_reactions(
        self,
        universal: cobra.Model,
        seed_metabolites: set[str],
    ) -> set[str]:
        """Find reactions reachable while allowing newly produced intermediates."""
        available = set(seed_metabolites)
        reachable: set[str] = set()
        directions = {
            reaction.id: self._reaction_directions(reaction) for reaction in universal.reactions
        }

        changed = True
        while changed:
            changed = False
            for reaction_id, reaction_directions in directions.items():
                for required, produced in reaction_directions:
                    if required <= available:
                        if reaction_id not in reachable or not produced <= available:
                            reachable.add(reaction_id)
                            before = len(available)
                            available.update(produced)
                            changed = changed or len(available) > before
                        break
        return reachable

    def _backward_relevant_reactions(
        self,
        universal: cobra.Model,
        target_metabolites: set[str],
    ) -> set[str]:
        """Find reactions that can contribute precursors to task targets."""
        if not target_metabolites:
            return set()

        required_metabolites = set(target_metabolites)
        relevant: set[str] = set()
        directions = {
            reaction.id: self._reaction_directions(reaction) for reaction in universal.reactions
        }

        changed = True
        while changed:
            changed = False
            for reaction_id, reaction_directions in directions.items():
                for required, produced in reaction_directions:
                    if produced & required_metabolites:
                        if reaction_id not in relevant or not required <= required_metabolites:
                            relevant.add(reaction_id)
                            before = len(required_metabolites)
                            required_metabolites.update(required)
                            changed = changed or len(required_metabolites) > before
                        break
        return relevant

    def _exclude_exchange_reactions_from_universal(
        self,
        universal: cobra.Model,
        tasks: list[MetabolicTask],
    ) -> cobra.Model:
        """Remove exchange/demand/sink reactions from solver candidates by default."""
        if not self._config.gapfill_exclude_exchange_reactions:
            return universal

        keep_reaction_ids: set[str] = set()
        universal_rxn_map, _, _ = self._task_runner._build_id_maps(universal)
        for task in tasks:
            if task.task_type != "Reaction":
                continue
            rxn_id = self._task_runner._resolve_reaction(task.target_id, universal_rxn_map)
            if rxn_id and not UniversalLoader.is_exchange_or_utility_reaction(rxn_id):
                keep_reaction_ids.add(rxn_id)

        filtered = cobra.Model(f"{universal.id}_no_exchange")
        filtered.name = f"{universal.name or universal.id} (exchange excluded)"
        filtered.compartments = dict(universal.compartments)
        filtered.add_reactions(
            [
                rxn.copy()
                for rxn in universal.reactions
                if rxn.id in keep_reaction_ids
                or not UniversalLoader.is_exchange_or_utility_reaction(rxn.id)
            ]
        )

        if len(filtered.reactions) == len(universal.reactions):
            return universal

        logger.info(
            "Excluded %d exchange/utility reaction(s) from gap-fill universal",
            len(universal.reactions) - len(filtered.reactions),
        )
        return filtered

    def _apply_gapfill_results(
        self,
        model: cobra.Model,
        reactions_to_add: list[cobra.Reaction],
        candidates: list[CandidateReaction],
    ) -> list[CandidateReaction]:
        """Apply gap-fill results to the model.

        1. Add reactions to the cobra model
        2. Find matching CandidateReaction objects
        3. Mark them as selected
        """
        # Build lookup for candidates
        candidate_map: dict[str, CandidateReaction] = {c.reaction.id: c for c in candidates}

        added_candidates: list[CandidateReaction] = []

        new_reactions: list[cobra.Reaction] = []
        for rxn in reactions_to_add:
            try:
                model.reactions.get_by_id(rxn.id)
            except KeyError:
                new_reactions.append(rxn.copy())

        if new_reactions:
            model.add_reactions(new_reactions)

        for rxn in reactions_to_add:
            if rxn.id in candidate_map:
                candidate = candidate_map[rxn.id]
            else:
                candidate = CandidateReaction(
                    reaction=convert_cobra_reaction(rxn),
                    source_model="gapfill",
                )
                candidate_map[rxn.id] = candidate
                candidates.append(candidate)
                logger.debug(
                    "Gap-filled reaction %s not found in candidates; created fallback",
                    rxn.id,
                )
            candidate.selected = True
            added_candidates.append(candidate)

        return added_candidates

    def _rollback_gapfill_results(
        self,
        model: cobra.Model,
        added_candidates: list[CandidateReaction],
        reaction_ids: list[str],
        added_by_id: dict[str, CandidateReaction],
    ) -> None:
        """Remove reaction additions from a failed/no-progress iteration."""
        reaction_id_set = set(reaction_ids)
        if not reaction_id_set:
            return

        for candidate in added_candidates:
            if candidate.reaction.id in reaction_id_set:
                candidate.selected = False
                added_by_id.pop(candidate.reaction.id, None)

        reactions_to_remove: list[cobra.Reaction] = []
        for reaction_id in reaction_id_set:
            try:
                reactions_to_remove.append(model.reactions.get_by_id(reaction_id))
            except KeyError:
                continue

        if reactions_to_remove:
            model.remove_reactions(reactions_to_remove, remove_orphans=True)
