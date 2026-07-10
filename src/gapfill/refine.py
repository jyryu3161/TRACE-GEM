"""Reusable task-aware refinement core.

This is the presentation-free heart of the gap-fill pipeline: load the
universal model, extract candidates, parse tasks, optionally evaluate evidence,
and run :class:`~src.gapfill.engine.GapFillEngine`. It returns data
(:class:`RefineOutcome`) rather than printing, so it can be driven from the CLI,
the "build then refine" path, and tests alike.

The interactive CLI (:func:`src.cli.async_gapfill_main`) keeps its own rich
stderr rendering; this core is what programmatic callers (e.g.
:meth:`src.build.build_engine.BuildEngine.refine`) use.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from src.core.models import (
    CandidateReaction,
    GapFillResult,
    MetabolicTask,
    ModelData,
    ReactionEvidence,
)
from src.utils.config import Config

logger = logging.getLogger("metataskgapfill.gapfill.refine")

ProgressCallback = Callable[[str, int, int, str], None]
LogCallback = Callable[[str], None]


def apply_base_medium_to_tasks(
    tasks: list[MetabolicTask],
    base_medium: dict[str, float],
) -> list[MetabolicTask]:
    """Merge a base medium into tasks; task-specific medium overrides it."""
    if not base_medium:
        return tasks

    merged_tasks: list[MetabolicTask] = []
    for task in tasks:
        merged_medium = dict(base_medium)
        merged_medium.update(task.medium)
        merged_tasks.append(
            MetabolicTask(
                task_id=task.task_id,
                task_type=task.task_type,
                target_id=task.target_id,
                medium=merged_medium,
                constraints=dict(task.constraints),
                expected_operator=task.expected_operator,
                expected_value=task.expected_value,
                description=task.description,
                category=task.category,
            )
        )
    return merged_tasks


@dataclass
class RefineOutcome:
    """Everything a caller needs to render or persist a refinement run."""

    gf_result: GapFillResult
    tasks: list[MetabolicTask] = field(default_factory=list)
    candidates: list[CandidateReaction] = field(default_factory=list)
    evidence_results: dict[str, ReactionEvidence] = field(default_factory=dict)
    base_medium: dict[str, float] = field(default_factory=dict)


async def refine_model_data(
    config: Config,
    model_data: ModelData,
    *,
    universal_path: str,
    tasks_path: str,
    base_medium: dict[str, float] | None = None,
    skip_evaluation: bool = False,
    include_exchange_gapfill: bool = False,
    progress_callback: ProgressCallback | None = None,
    log: LogCallback | None = None,
    evidence_engine=None,
) -> RefineOutcome:
    """Run the full task-aware gap-fill pipeline on ``model_data``.

    Args:
        config: App config (its ``kegg_organism_code`` drives organism filtering).
        model_data: Model to refine; ``model_data.cobra_model`` is modified in place.
        universal_path: Path to universal model (JSON/SBML).
        tasks_path: Path to metabolic tasks CSV.
        base_medium: Pre-resolved base medium ({EX_id: lower_bound}); merged into
            each task (task-specific medium wins).
        skip_evaluation: Skip evidence evaluation of model + candidate reactions.
        include_exchange_gapfill: Allow exchange/demand/sink reactions as candidates.
        progress_callback: ``(phase, current, total, detail)`` forwarded to the engine.
        log: Optional milestone logger ``(str) -> None``.
        evidence_engine: Optional live EvidenceEngine to reuse (e.g. from the GUI).
            If ``None``, a fresh engine is created, initialized, and closed here.

    Returns:
        RefineOutcome with the GapFillResult, the (medium-merged) tasks, the
        extracted candidates, and any evidence results.
    """
    from src.core.task_parser import TaskParser
    from src.core.universal_loader import UniversalLoader
    from src.evidence.engine import EvidenceEngine
    from src.gapfill.engine import GapFillEngine

    if model_data.cobra_model is None:
        raise ValueError("model_data has no cobra_model; cannot refine")

    _log = log or (lambda _msg: None)

    _log("Loading universal model...")
    loader = UniversalLoader()
    universal_model = loader.load(universal_path)
    config.gapfill_exclude_exchange_reactions = not include_exchange_gapfill
    _log(
        f"Universal model: {len(universal_model.reactions)} reactions, "
        f"{len(universal_model.metabolites)} metabolites"
    )

    candidates = loader.extract_candidates(
        universal_model,
        model_data,
        exclude_exchange_reactions=config.gapfill_exclude_exchange_reactions,
    )
    _log(f"{len(candidates)} candidate reactions extracted")

    task_parser = TaskParser()
    tasks = task_parser.parse(tasks_path)
    base_medium = base_medium or {}
    tasks = apply_base_medium_to_tasks(tasks, base_medium)
    _log(f"{len(tasks)} tasks loaded; base medium: {len(base_medium)} exchanges")

    evidence_results: dict[str, ReactionEvidence] = {}
    own_engine = evidence_engine is None
    engine = evidence_engine or EvidenceEngine(config)

    try:
        # Initialize inside the try so a failure during init still closes the
        # engine (aiohttp session / sqlite cache) we created.
        if own_engine:
            await engine.initialize()

        # KEGG evidence is computed only for gap-fill candidates (to weight
        # which universal reactions to add). Model quality is judged by tasks,
        # not by per-reaction evidence.
        if skip_evaluation:
            _log("Skipping candidate evidence evaluation")
        else:
            _log(f"Evaluating {len(candidates)} candidate reactions...")

            def _cand_progress(c: int, t: int, rxn_id: str) -> None:
                if progress_callback:
                    progress_callback("evaluating_candidates", c, t, rxn_id)

            evidence_results = await engine.evaluate_candidates_batch(
                candidates, progress_callback=_cand_progress
            )

        gapfill_engine = GapFillEngine(config)
        try:
            # initialize inside the try so a failure still closes the engine
            # (OrganismFilter's aiohttp session).
            await gapfill_engine.initialize(
                organism_code=config.kegg_organism_code,
                cache_manager=engine.cache_manager,
                mapping_data=engine.mapping_data,
            )
            gf_result = await gapfill_engine.run(
                user_model=model_data.cobra_model,
                universal_model=universal_model,
                candidates=candidates,
                tasks=tasks,
                evidence_results=evidence_results,
                progress_callback=progress_callback,
            )
        finally:
            await gapfill_engine.close()
    finally:
        if own_engine:
            await engine.close()

    _log(
        f"Gap-fill complete: {len(gf_result.added_reactions)} reactions added, "
        f"{gf_result.tasks_fixed}/{gf_result.total_tasks} tasks fixed"
    )
    return RefineOutcome(
        gf_result=gf_result,
        tasks=tasks,
        candidates=candidates,
        evidence_results=evidence_results,
        base_medium=base_medium,
    )
