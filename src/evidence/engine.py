"""Evidence collection engine — orchestrates multi-source reaction verification."""

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
    EvaluationStatus,
    Reaction,
    ReactionEvidence,
)
from src.evidence.scoring import ConfidenceScorer
from src.utils.config import Config
from src.utils.constants import BATCH_SIZE

logger = logging.getLogger("gem_evaluator.evidence")


class EvidenceEngine:
    """Orchestrates multi-source evidence collection with offline ID mapping."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._cache: CacheManager | None = None
        self._kegg: KEGGClient | None = None
        self._gemini: Any = None
        self._perplexity: Any = None
        self._mapper: IdentifierMapper | None = None
        self._mapping_data: MappingData | None = None
        self._scorer = ConfidenceScorer(config.weights)
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

        # Initialize Gemini client if API key is available
        if self._config.gemini_api_key and self._config.enable_gemini:
            try:
                from src.api.gemini_client import GeminiClient

                self._gemini = GeminiClient(
                    api_key=self._config.gemini_api_key,
                    cache_manager=self._cache,
                )
                logger.info("Gemini client initialized")
            except Exception as e:
                logger.warning("Failed to initialize Gemini client: %s", e)

        # Initialize Perplexity client if API key is available
        if self._config.perplexity_api_key and self._config.enable_perplexity:
            try:
                from src.api.perplexity_client import PerplexityClient

                self._perplexity = PerplexityClient(
                    api_key=self._config.perplexity_api_key,
                    cache_manager=self._cache,
                )
                logger.info("Perplexity client initialized")
            except Exception as e:
                logger.warning("Failed to initialize Perplexity client: %s", e)

    async def close(self) -> None:
        """Close all API clients and cache."""
        if self._closed:
            return
        if self._kegg:
            await self._kegg.close()
            self._kegg = None
        if self._gemini:
            await self._gemini.close()
            self._gemini = None
        if self._perplexity:
            await self._perplexity.close()
            self._perplexity = None
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

    async def evaluate_reaction(self, reaction: Reaction) -> ReactionEvidence:
        """Evaluate a single reaction using KEGG + optional LLM verification."""
        evidence = ReactionEvidence(reaction_id=reaction.id)
        evidence.status = EvaluationStatus.IN_PROGRESS

        try:
            assert self._mapper is not None, "Engine not initialized"
            assert self._kegg is not None, "Engine not initialized"

            # Step 1: Resolve external IDs (offline)
            ext_ids = await self._mapper.resolve(reaction)
            evidence.ec_numbers = ext_ids.ec_numbers
            evidence.kegg_reaction_ids = ext_ids.kegg_reaction_ids

            # Step 2: KEGG verification
            kegg_items = await self._kegg.check_evidence(
                reaction,
                kegg_reaction_ids=ext_ids.kegg_reaction_ids,
                model_substrates_kegg=ext_ids.kegg_substrate_ids,
                model_products_kegg=ext_ids.kegg_product_ids,
                ec_numbers=ext_ids.ec_numbers,
            )
            evidence.items.extend(kegg_items)

            # Step 3: Extract match ratios from raw_data
            kegg_parsed_data = None
            for item in kegg_items:
                if item.raw_data:
                    sub_match = item.raw_data.get("substrate_match")
                    prod_match = item.raw_data.get("product_match")
                    if sub_match is not None:
                        evidence.substrate_match_ratio = sub_match
                    if prod_match is not None:
                        evidence.product_match_ratio = prod_match
                    kegg_parsed_data = item.raw_data.get("kegg_parsed")

            # Resolve metabolite names for LLM prompts
            reactant_names: dict[str, str] = {}
            product_names: dict[str, str] = {}
            for met_id in reaction.reactants:
                name = self._mapper.get_metabolite_name(met_id) if self._mapper else None
                reactant_names[met_id] = name or met_id
            for met_id in reaction.products:
                name = self._mapper.get_metabolite_name(met_id) if self._mapper else None
                product_names[met_id] = name or met_id

            # Step 4: Gemini verification (if KEGG match exists)
            if self._gemini and kegg_parsed_data:
                try:
                    gemini_item = await self._gemini.verify_reaction_match(
                        reaction,
                        kegg_parsed_data,
                        evidence.substrate_match_ratio,
                        evidence.product_match_ratio,
                        self._config.organism_name,
                        reactant_names=reactant_names,
                        product_names=product_names,
                    )
                    evidence.items.append(gemini_item)
                except Exception as e:
                    logger.warning("Gemini verification failed for %s: %s", reaction.id, e)

            # Step 5: Perplexity verification
            if self._perplexity:
                try:
                    pplx_item = await self._perplexity.verify_reaction_existence(
                        reaction,
                        self._config.organism_name,
                        ext_ids.ec_numbers,
                        reactant_names=reactant_names,
                        product_names=product_names,
                    )
                    evidence.items.append(pplx_item)
                except Exception as e:
                    logger.warning("Perplexity verification failed for %s: %s", reaction.id, e)

            # Step 6: Score
            self._scorer.score(evidence)
            evidence.status = EvaluationStatus.EVALUATED

        except Exception as e:
            logger.error("Evaluation failed for %s: %s", reaction.id, e)
            evidence.status = EvaluationStatus.ERROR
            evidence.error_message = str(e)

        self._results[reaction.id] = evidence
        return evidence

    async def evaluate_batch(
        self,
        reactions: list[Reaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, ReactionEvidence]:
        """Evaluate a batch of reactions with progress reporting."""
        total = len(reactions)
        batch_size = max(1, self._config.batch_size or BATCH_SIZE)
        max_concurrent = max(1, self._config.max_concurrent)
        completed = 0

        for i in range(0, total, batch_size):
            if cancel_event and cancel_event.is_set():
                logger.info("Evaluation cancelled at %d/%d", i, total)
                break

            batch = reactions[i : i + batch_size]
            semaphore = asyncio.Semaphore(max_concurrent)

            async def _evaluate_with_limit(reaction: Reaction) -> None:
                nonlocal completed
                if cancel_event and cancel_event.is_set():
                    return
                async with semaphore:
                    if cancel_event and cancel_event.is_set():
                        return
                    await self.evaluate_reaction(reaction)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, reaction.id)

            tasks = [asyncio.create_task(_evaluate_with_limit(r)) for r in batch]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in task_results:
                if isinstance(result, Exception):
                    logger.warning("Batch subtask failed: %s", result)

            logger.info("Evaluated %d/%d reactions", completed, total)

        return dict(self._results)

    def get_result(self, reaction_id: str) -> ReactionEvidence | None:
        """Get cached evaluation result for a reaction."""
        return self._results.get(reaction_id)

    def get_all_results(self) -> dict[str, ReactionEvidence]:
        """Get all cached evaluation results."""
        return dict(self._results)

    def clear_results(self) -> None:
        """Clear all cached results."""
        self._results.clear()
