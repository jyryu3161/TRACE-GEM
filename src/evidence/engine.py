"""Evidence collection engine — orchestrates KEGG/BiGG reaction verification."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from src.api.kegg_client import KEGGClient
from src.cache.cache_manager import CacheManager
from src.core.id_mapper import IdentifierMapper
from src.core.mapping_data import MappingData
from src.core.models import (
    CandidateReaction,
    EvaluationStatus,
    Reaction,
    ReactionEvidence,
)
from src.evidence.scoring import ConfidenceScorer
from src.utils.config import Config
from src.utils.constants import BATCH_SIZE

logger = logging.getLogger("metataskgapfill.evidence")


class EvidenceBatchError(RuntimeError):
    """Raised when a candidate evidence batch is too incomplete to use safely."""


class EvidenceEngine:
    """Orchestrates KEGG evidence collection with offline ID mapping."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._cache: CacheManager | None = None
        self._kegg: KEGGClient | None = None
        self._bigg: Any = None
        self._mapper: IdentifierMapper | None = None
        self._mapping_data: MappingData | None = None
        self._scorer = ConfidenceScorer()
        self._results: dict[str, ReactionEvidence] = {}
        self._closed = False

    async def initialize(self) -> None:
        """Initialize offline mappings, cache, and API clients."""
        self._closed = False
        self._mapping_data = MappingData.load()
        self._cache = CacheManager()
        await self._cache.initialize()

        self._kegg = KEGGClient(
            organism_code=self._config.kegg_organism_code,
            cache_manager=self._cache,
        )
        self._mapper = IdentifierMapper(self._mapping_data)
        # Evidence is KEGG-only. BiGG is not an evidence source; its KEGG↔BiGG
        # reaction mapping (via MappingData) is used only by gap-fill.

    async def close(self) -> None:
        """Close all API clients and cache."""
        if self._closed:
            return
        for client_attr in (
            "_kegg",
            "_bigg",
        ):
            client = getattr(self, client_attr, None)
            if client:
                await client.close()
                setattr(self, client_attr, None)
        if self._cache:
            await self._cache.close()
            self._cache = None
        self._mapper = None
        self._mapping_data = None
        self._closed = True

    @property
    def mapper(self) -> IdentifierMapper | None:
        """Expose the identifier mapper for external use."""
        return self._mapper

    @property
    def cache_manager(self) -> CacheManager | None:
        """Expose cache manager for external use (e.g., gap-fill engine)."""
        return self._cache

    @property
    def mapping_data(self) -> MappingData | None:
        """Expose mapping data for external use."""
        return self._mapping_data

    async def evaluate_candidate(self, candidate: CandidateReaction) -> ReactionEvidence:
        """Evaluate a single candidate reaction from a universal model.

        Uses ``resolve(universal=True)`` for annotation-format differences.
        Evidence is KEGG-only; a candidate's universal-model membership is not
        treated as evidence of its identity.
        """
        reaction = candidate.reaction
        evidence = ReactionEvidence(reaction_id=reaction.id)
        evidence.status = EvaluationStatus.IN_PROGRESS

        try:
            assert self._mapper is not None, "Engine not initialized"
            assert self._kegg is not None, "Engine not initialized"

            # Step 1: Resolve external IDs using universal annotation format
            ext_ids = await self._mapper.resolve(reaction, universal=True)
            evidence.ec_numbers = ext_ids.ec_numbers
            evidence.kegg_reaction_ids = ext_ids.kegg_reaction_ids

            # Steps 2-3: KEGG verification (KEGG is the only evidence source)
            await self._run_kegg_verification(reaction, ext_ids, evidence)

            # Step 4: Score (rule-based, KEGG-only)
            self._scorer.score(evidence)
            evidence.status = EvaluationStatus.EVALUATED

        except Exception as e:
            logger.error("Candidate evaluation failed for %s: %s", reaction.id, e)
            evidence.status = EvaluationStatus.ERROR
            evidence.error_message = str(e)

        self._results[reaction.id] = evidence
        return evidence

    async def evaluate_candidates_batch(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: asyncio.Event | Any | None = None,
    ) -> dict[str, ReactionEvidence]:
        """Evaluate a batch of candidate reactions with progress reporting."""
        requested_ids = {candidate.reaction.id for candidate in candidates}
        for reaction_id in requested_ids:
            self._results.pop(reaction_id, None)

        async def _evaluate_item(candidate: CandidateReaction) -> str:
            await self.evaluate_candidate(candidate)
            return candidate.reaction.id

        results = await self._run_batch(
            items=candidates,
            evaluate_fn=_evaluate_item,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            label="candidates",
        )
        errors = [
            evidence for evidence in results.values() if evidence.status is EvaluationStatus.ERROR
        ]
        error_fraction = len(errors) / len(results) if results else 0.0
        allowed = min(1.0, max(0.0, self._config.candidate_evidence_max_error_fraction))
        cancelled = bool(cancel_event and cancel_event.is_set())
        if not cancelled and error_fraction > allowed:
            examples = ", ".join(evidence.reaction_id for evidence in errors[:5])
            raise EvidenceBatchError(
                f"Candidate evidence failed for {len(errors)}/{len(results)} reactions "
                f"({error_fraction:.1%}; allowed {allowed:.1%}). "
                f"Examples: {examples}"
            )
        return results

    # ── Shared pipeline helpers ──────────────────────────────────────

    async def _run_kegg_verification(
        self,
        reaction: Reaction,
        ext_ids: Any,
        evidence: ReactionEvidence,
    ) -> None:
        """Run KEGG verification and extract match ratios (Steps 2-3)."""
        assert self._kegg is not None
        kegg_items = await self._kegg.check_evidence(
            reaction,
            kegg_reaction_ids=ext_ids.kegg_reaction_ids,
            model_substrates_kegg=ext_ids.kegg_substrate_ids,
            model_products_kegg=ext_ids.kegg_product_ids,
            model_substrate_stoichiometry=ext_ids.kegg_substrate_stoichiometry,
            model_product_stoichiometry=ext_ids.kegg_product_stoichiometry,
            model_stoichiometry_complete=ext_ids.kegg_stoichiometry_complete,
            ec_numbers=ext_ids.ec_numbers,
        )
        evidence.items.extend(kegg_items)

        # The KEGG client returns a single best item; lift its provenance states
        # onto the evidence so the scorer can apply the rule-based tier.
        best = kegg_items[0] if kegg_items else None
        raw = best.raw_data if (best and best.raw_data) else {}
        evidence.kegg_anchored = bool(raw.get("kegg_anchored", False))
        evidence.reconciliation_state = raw.get("reconciliation_state", "unverifiable")
        evidence.ec_concordance_state = raw.get("ec_concordance_state", "unknown")
        evidence.stoichiometry_state = raw.get("stoichiometry_state", "unverifiable")

        sub_match = raw.get("substrate_match")
        prod_match = raw.get("product_match")
        if sub_match is not None:
            evidence.substrate_match_ratio = sub_match
        if prod_match is not None:
            evidence.product_match_ratio = prod_match

        # A KEGG reaction ID counts as "verified" only if its entry was retrieved
        # and did not contradict the model reaction. A KEGG ID rejected as a
        # mismatch must not launder into the no-KEGG gap-fill penalty.
        if evidence.kegg_anchored and evidence.reconciliation_state != "none_contradictory":
            kid = raw.get("kegg_id")
            if kid:
                evidence.verified_kegg_reaction_ids = [kid]

    async def _run_batch(
        self,
        items: list,
        evaluate_fn: Callable,
        progress_callback: Callable[[int, int, str], None] | None,
        cancel_event: asyncio.Event | None,
        label: str,
    ) -> dict[str, ReactionEvidence]:
        """Shared batch evaluation with semaphore concurrency control."""
        total = len(items)
        batch_size = max(1, self._config.batch_size or BATCH_SIZE)
        max_concurrent = max(1, self._config.max_concurrent)
        completed = 0
        completed_ids: set[str] = set()

        for i in range(0, total, batch_size):
            if cancel_event and cancel_event.is_set():
                logger.info("%s evaluation cancelled at %d/%d", label.title(), i, total)
                break

            batch = items[i : i + batch_size]
            semaphore = asyncio.Semaphore(max_concurrent)

            async def _evaluate_with_limit(item: Any) -> None:
                nonlocal completed
                if cancel_event and cancel_event.is_set():
                    return
                async with semaphore:  # noqa: B023
                    if cancel_event and cancel_event.is_set():
                        return
                    item_id = await evaluate_fn(item)
                completed_ids.add(item_id)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, item_id)

            tasks = [asyncio.create_task(_evaluate_with_limit(item)) for item in batch]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in task_results:
                if isinstance(result, Exception):
                    logger.warning("Batch subtask failed (%s): %s", label, result)

            logger.info("Evaluated %d/%d %s", completed, total, label)

        return {
            reaction_id: self._results[reaction_id]
            for reaction_id in completed_ids
            if reaction_id in self._results
        }

    def get_result(self, reaction_id: str) -> ReactionEvidence | None:
        """Get cached evaluation result for a reaction."""
        return self._results.get(reaction_id)

    def get_all_results(self) -> dict[str, ReactionEvidence]:
        """Get all cached evaluation results."""
        return dict(self._results)

    def clear_results(self) -> None:
        """Clear all cached results."""
        self._results.clear()
