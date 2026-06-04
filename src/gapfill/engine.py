"""Gap-filling engine orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

import cobra

from src.cache.cache_manager import CacheManager
from src.core.cobra_utils import convert_cobra_reaction
from src.core.mapping_data import MappingData
from src.core.models import (
    CandidateReaction,
    GapFillResult,
    MetabolicTask,
    ReactionEvidence,
    TaskResult,
)
from src.core.task_parser import TaskRunner
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

    def __init__(self, config: Config) -> None:
        self._config = config
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
        preloaded_before: list[TaskResult] | None = None,
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
            preloaded_before: Preloaded Phase 1 results for resume.

        Returns:
            GapFillResult with before/after task results and added reactions.
        """
        result = GapFillResult(total_tasks=len(tasks))
        result.all_candidates = list(candidates)

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
        elif preloaded_before:
            result.task_results_before = preloaded_before
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
            if self._organism_filter:
                _progress("filtering", 0, len(candidates), "Filtering by organism...")
                await self._organism_filter.filter_candidates(
                    candidates,
                    progress_callback=lambda c, t, d: _progress("filtering", c, t, d),
                )
                logger.info("Phase 2 complete: organism filtering done")

            # Calculate penalties
            penalties = self._penalty_calc.calculate_batch(candidates, evidence_results)
            # Update candidate penalties
            for candidate in candidates:
                if candidate.reaction.id in penalties:
                    candidate.penalty = penalties[candidate.reaction.id]

            result.all_candidates = list(candidates)
            result.completed_phase = 2

            if _is_cancelled():
                result.is_partial = True
                return result
        else:
            # Still need penalties for Phase 3
            penalties = self._penalty_calc.calculate_batch(candidates, evidence_results)
            for candidate in candidates:
                if candidate.reaction.id in penalties:
                    candidate.penalty = penalties[candidate.reaction.id]

        latest_after_results: list[TaskResult] | None = None
        gapfill_universal = self._prune_universal_for_gapfill(
            universal_model,
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
            current_results = result.task_results_before
            added_by_id: dict[str, CandidateReaction] = {}
            max_iterations = max(1, self._config.gapfill_iterations)
            prev_passed = sum(1 for r in current_results if r.passed)

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
                    evidence_results[c.reaction.id].confidence_score
                    if c.reaction.id in evidence_results
                    else 0.0
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
                result.is_partial = True
                return result

        # Phase 4: GPR assignment
        if start_phase <= 4:
            if self._gpr_assigner and result.added_reactions:
                _progress("assigning_gpr", 0, len(result.added_reactions), "Assigning GPR...")
                await self._gpr_assigner.assign_batch(
                    result.added_reactions,
                    progress_callback=lambda c, t, d: _progress("assigning_gpr", c, t, d),
                )
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

    def _run_tasks(
        self,
        model: cobra.Model,
        tasks: list[MetabolicTask],
        phase: str = "before",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[TaskResult]:
        """Run all metabolic tasks and tag results with phase."""
        results = self._task_runner.run_all(
            model, tasks, progress_callback=progress_callback
        )
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
                reactions = self._gapfill_for_task(
                    model, universal, task, penalties, required
                )
            except RuntimeError:
                # Solver infeasibility near the requested bound: retry at a
                # relaxed bound, but only keep reactions that genuinely satisfy
                # the task's real threshold (see _retry_gapfill).
                reactions = self._retry_gapfill(
                    model, universal, task, penalties, required, result
                )
            except Exception as e:
                logger.warning("Gap-fill failed for task %s: %s", task.task_id, e)
                result.infeasible_tasks.append(task.task_id)
                continue

            for rxn in reactions:
                if rxn.id not in all_added:
                    all_added[rxn.id] = rxn

        if progress_callback:
            progress_callback(
                len(failed_tasks), len(failed_tasks), "Gap-fill complete"
            )

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
    ) -> list[cobra.Reaction]:
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
            result.infeasible_tasks.append(task.task_id)
            return []

        try:
            reactions = self._gapfill_for_task(
                model, universal, task, penalties, retry_bound
            )
        except Exception as e:
            logger.warning("Task %s infeasible: %s", task.task_id, e)
            result.infeasible_tasks.append(task.task_id)
            return []

        if reactions and not self._reactions_satisfy_task(
            model, universal, task, reactions
        ):
            logger.info(
                "Task %s only reached relaxed bound %.4g (< required %.4g); "
                "discarding %d spurious reaction(s)",
                task.task_id,
                retry_bound,
                required,
                len(reactions),
            )
            result.infeasible_tasks.append(task.task_id)
            return []
        return reactions

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
            test_model = self._task_runner.prepare_task_model(
                test_model, task, copy_model=False
            )
            existing = set(test_model.reactions.list_attr("id"))
            to_add = [r.copy() for r in reactions if r.id not in existing]
            if to_add:
                test_model.add_reactions(to_add)
            solution = test_model.optimize()
            actual = (
                solution.objective_value
                if solution.status != "infeasible"
                and solution.objective_value is not None
                else 0.0
            )
        except Exception as e:
            logger.debug("Validation solve failed for %s: %s", task.task_id, e)
            return False

        return self._task_runner._check_expected(
            actual, task.expected_operator, task.expected_value
        )

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
        test_model = model.copy()
        preseeded = self._preseed_missing_task_target(test_model, universal, task)
        try:
            test_model = self._task_runner.prepare_task_model(
                test_model, task, copy_model=False
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        # Run gap-fill
        result = cobra.flux_analysis.gapfilling.gapfill(
            test_model,
            universal,
            lower_bound=lower_bound,
            penalties=penalties,
            demand_reactions=False,
        )

        if not result or not result[0]:
            return preseeded

        reactions_by_id = {rxn.id: rxn for rxn in preseeded}
        for rxn in result[0]:
            reactions_by_id.setdefault(rxn.id, rxn)
        return list(reactions_by_id.values())

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
                raise RuntimeError(
                    f"Reaction '{task.target_id}' not found in model or universal"
                )

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
                raise RuntimeError(
                    f"Metabolite '{task.target_id}' not found in model or universal"
                )

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

        keep_reaction_ids: set[str] = set()
        universal_rxn_map, universal_met_map, _ = self._task_runner._build_id_maps(universal)

        for task in tasks:
            if task.task_type == "Reaction":
                rxn_id = self._task_runner._resolve_reaction(task.target_id, universal_rxn_map)
                if rxn_id:
                    keep_reaction_ids.add(rxn_id)
            elif task.task_type == "Metabolite":
                met_id = self._task_runner._resolve_metabolite(task.target_id, universal_met_map)
                if met_id:
                    allowed_metabolites.add(met_id)

        for rxn in universal.reactions:
            metabolite_ids = {met.id for met in rxn.metabolites}
            if metabolite_ids and metabolite_ids <= allowed_metabolites:
                keep_reaction_ids.add(rxn.id)

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
        candidate_map: dict[str, CandidateReaction] = {
            c.reaction.id: c for c in candidates
        }

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
