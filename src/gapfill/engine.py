"""Gap-filling engine orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Callable

import cobra

from src.cache.cache_manager import CacheManager
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
from src.utils.constants import GAPFILL_LOWER_BOUND

logger = logging.getLogger("gem_evaluator.gapfill.engine")


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
    ) -> GapFillResult:
        """Execute the full gap-filling pipeline.

        Args:
            user_model: The user's cobra Model (will be modified in place).
            universal_model: The universal cobra Model for gap-filling.
            candidates: Candidate reactions extracted from universal model.
            tasks: Metabolic tasks for testing.
            evidence_results: Evidence scores for candidates.
            progress_callback: Optional (phase, current, total, detail) callback.

        Returns:
            GapFillResult with before/after task results and added reactions.
        """
        result = GapFillResult(total_tasks=len(tasks))

        def _progress(phase: str, current: int, total: int, detail: str) -> None:
            if progress_callback:
                progress_callback(phase, current, total, detail)

        # Phase 1: Initial task testing
        _progress("testing_before", 0, len(tasks), "Running initial tests...")
        result.task_results_before = self._run_tasks(
            user_model,
            tasks,
            phase="before",
            progress_callback=lambda c, t, d: _progress("testing_before", c, t, d),
        )

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
            return result

        # Phase 2: Organism filtering
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

        # Phase 3: Gap-filling
        _progress("gap_filling", 0, len(failed_tasks), "Running gap-fill...")
        added_reactions = await self._run_gapfill(
            user_model,
            universal_model,
            failed_tasks,
            penalties,
            result,
            progress_callback=lambda c, t, d: _progress("gap_filling", c, t, d),
        )

        # Apply gap-fill results to the model
        if added_reactions:
            result.added_reactions = self._apply_gapfill_results(
                user_model, added_reactions, candidates
            )
            # Sort added reactions by evidence score descending
            result.added_reactions.sort(
                key=lambda c: (
                    evidence_results[c.reaction.id].confidence_score
                    if c.reaction.id in evidence_results
                    else 0.0
                ),
                reverse=True,
            )
            logger.info(
                "Phase 3 complete: %d reactions added to model",
                len(result.added_reactions),
            )
        else:
            logger.info("Phase 3 complete: no reactions added")

        # Phase 4: GPR assignment
        if self._gpr_assigner and result.added_reactions:
            _progress("assigning_gpr", 0, len(result.added_reactions), "Assigning GPR...")
            await self._gpr_assigner.assign_batch(
                result.added_reactions,
                progress_callback=lambda c, t, d: _progress("assigning_gpr", c, t, d),
            )
            logger.info("Phase 4 complete: GPR assignment done")

        # Phase 5: Final task testing
        _progress("testing_after", 0, len(tasks), "Running final tests...")
        result.task_results_after = self._run_tasks(
            user_model,
            tasks,
            phase="after",
            progress_callback=lambda c, t, d: _progress("testing_after", c, t, d),
        )

        # Calculate tasks fixed
        before_failed = {r.task.task_id for r in result.task_results_before if not r.passed}
        after_passed = {r.task.task_id for r in result.task_results_after if r.passed}
        result.tasks_fixed = len(before_failed & after_passed)

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
        lower_bound = self._config.gapfill_lower_bound

        for i, task in enumerate(failed_tasks):
            if progress_callback:
                progress_callback(i, len(failed_tasks), f"Gap-filling for task {task.task_id}")

            try:
                reactions = self._gapfill_for_task(
                    model, universal, task, penalties, lower_bound
                )
                for rxn in reactions:
                    if rxn.id not in all_added:
                        all_added[rxn.id] = rxn

            except RuntimeError:
                # Retry with relaxed lower bound
                try:
                    reactions = self._gapfill_for_task(
                        model, universal, task, penalties, 0.01
                    )
                    for rxn in reactions:
                        if rxn.id not in all_added:
                            all_added[rxn.id] = rxn
                except (RuntimeError, Exception) as e:
                    logger.warning(
                        "Task %s infeasible: %s", task.task_id, e
                    )
                    result.infeasible_tasks.append(task.task_id)

            except Exception as e:
                logger.warning(
                    "Gap-fill failed for task %s: %s", task.task_id, e
                )
                result.infeasible_tasks.append(task.task_id)

        if progress_callback:
            progress_callback(
                len(failed_tasks), len(failed_tasks), "Gap-fill complete"
            )

        result.iterations += 1
        return list(all_added.values())

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

        # Apply task medium: close all exchanges, then open specified ones
        for rxn in test_model.reactions:
            if rxn.id.startswith("EX_"):
                rxn.lower_bound = 0.0

        for rxn_id, lb in task.medium.items():
            try:
                rxn = test_model.reactions.get_by_id(rxn_id)
                rxn.lower_bound = lb
            except KeyError:
                pass

        # Apply task constraints
        for rxn_id, (lb, ub) in task.constraints.items():
            try:
                rxn = test_model.reactions.get_by_id(rxn_id)
                rxn.lower_bound = lb
                rxn.upper_bound = ub
            except KeyError:
                pass

        # Set objective based on task type
        if task.task_type == "Metabolite":
            demand_id = f"DM_{task.target_id}"
            try:
                met = test_model.metabolites.get_by_id(task.target_id)
            except KeyError:
                raise RuntimeError(
                    f"Metabolite '{task.target_id}' not found in model"
                )
            demand_rxn = cobra.Reaction(demand_id)
            demand_rxn.add_metabolites({met: -1.0})
            demand_rxn.lower_bound = 0.0
            demand_rxn.upper_bound = 1000.0
            test_model.add_reactions([demand_rxn])
            test_model.objective = demand_id
        elif task.task_type == "Reaction":
            try:
                test_model.reactions.get_by_id(task.target_id)
            except KeyError:
                raise RuntimeError(
                    f"Reaction '{task.target_id}' not found in model"
                )
            test_model.objective = task.target_id

        # Run gap-fill
        result = cobra.flux_analysis.gapfilling.gapfill(
            test_model,
            universal,
            lower_bound=lower_bound,
            penalties=penalties,
        )

        if not result or not result[0]:
            return []

        return list(result[0])

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

        # Filter out reactions already in model
        new_reactions = [
            rxn for rxn in reactions_to_add
            if rxn.id not in model.reactions
        ]

        if new_reactions:
            model.add_reactions(new_reactions)

        for rxn in reactions_to_add:
            if rxn.id in candidate_map:
                candidate = candidate_map[rxn.id]
                candidate.selected = True
                added_candidates.append(candidate)
            else:
                logger.debug(
                    "Gap-filled reaction %s not found in candidates", rxn.id
                )

        return added_candidates
