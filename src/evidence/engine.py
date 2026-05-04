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
    CandidateReaction,
    EvaluationStatus,
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
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
        self._bigg: Any = None
        self._uniprot: Any = None
        self._pubmed: Any = None
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

        # Initialize BiGG local lookup (replaces REST API)
        if self._config.enable_bigg:
            try:
                from src.api.bigg_lookup import BiGGLookup

                self._bigg = BiGGLookup()
                self._bigg.load()
                logger.info(
                    "BiGG local lookup initialized: %d reactions, %d metabolites",
                    self._bigg.reaction_count,
                    self._bigg.metabolite_count,
                )
            except Exception as e:
                logger.warning("Failed to initialize BiGG lookup: %s", e)

        # Initialize UniProt client
        if self._config.enable_uniprot:
            try:
                from src.api.uniprot_client import UniProtClient

                self._uniprot = UniProtClient(
                    taxonomy_id=self._config.uniprot_taxonomy_id,
                    cache_manager=self._cache,
                )
                logger.info("UniProt client initialized")
            except Exception as e:
                logger.warning("Failed to initialize UniProt client: %s", e)

        # Initialize PubMed client
        if self._config.enable_pubmed:
            try:
                from src.api.pubmed_client import PubMedClient

                self._pubmed = PubMedClient(
                    email=self._config.pubmed_email,
                    api_key=self._config.pubmed_api_key,
                    cache_manager=self._cache,
                )
                logger.info("PubMed client initialized")
            except Exception as e:
                logger.warning("Failed to initialize PubMed client: %s", e)

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
        for client_attr in (
            "_kegg",
            "_bigg",
            "_uniprot",
            "_pubmed",
            "_gemini",
            "_perplexity",
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

    async def evaluate_reaction(self, reaction: Reaction) -> ReactionEvidence:
        """Evaluate a single reaction against all enabled sources."""
        evidence = ReactionEvidence(reaction_id=reaction.id)
        evidence.status = EvaluationStatus.IN_PROGRESS

        try:
            assert self._mapper is not None, "Engine not initialized"
            assert self._kegg is not None, "Engine not initialized"

            # Step 1: Resolve external IDs (offline)
            ext_ids = await self._mapper.resolve(reaction)
            evidence.ec_numbers = ext_ids.ec_numbers
            evidence.kegg_reaction_ids = ext_ids.kegg_reaction_ids

            # Steps 2-3: KEGG verification + extract match ratios
            kegg_parsed_data = await self._run_kegg_verification(
                reaction, ext_ids, evidence
            )

            # Step 4: BiGG verification
            if self._bigg:
                try:
                    bigg_items = await self._bigg.check_evidence(
                        reaction,
                        bigg_id=reaction.id,
                    )
                    evidence.items.extend(bigg_items)
                except Exception as e:
                    logger.warning("BiGG verification failed for %s: %s", reaction.id, e)

            # Steps 5-9: Common evidence pipeline
            await self._run_evidence_pipeline(
                reaction, ext_ids, evidence, kegg_parsed_data
            )

            # Step 10: Score
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
        cancel_event: asyncio.Event | Any | None = None,
    ) -> dict[str, ReactionEvidence]:
        """Evaluate a batch of reactions with progress reporting."""

        async def _evaluate_item(reaction: Reaction) -> str:
            await self.evaluate_reaction(reaction)
            return reaction.id

        return await self._run_batch(
            items=reactions,
            evaluate_fn=_evaluate_item,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            label="reactions",
        )

    async def evaluate_candidate(self, candidate: CandidateReaction) -> ReactionEvidence:
        """Evaluate a single candidate reaction from a universal model.

        Differences from evaluate_reaction():
        - Uses resolve(universal=True) for annotation format differences
        - BiGG verification returns STRONG automatically (reaction is from BiGG universal)
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

            # Steps 2-3: KEGG verification + extract match ratios
            kegg_parsed_data = await self._run_kegg_verification(
                reaction, ext_ids, evidence
            )

            # Step 4: BiGG verification — automatic STRONG for universal model candidates
            evidence.items.append(
                EvidenceItem(
                    source=EvidenceSource.BIGG,
                    strength=EvidenceStrength.STRONG,
                    description=(
                        f"Reaction exists in BiGG universal model "
                        f"(source: {candidate.source_model})"
                    ),
                    url=f"http://bigg.ucsd.edu/universal/reactions/{reaction.id}",
                )
            )

            # Steps 5-9: Common evidence pipeline
            await self._run_evidence_pipeline(
                reaction, ext_ids, evidence, kegg_parsed_data
            )

            # Step 10: Score
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

        async def _evaluate_item(candidate: CandidateReaction) -> str:
            await self.evaluate_candidate(candidate)
            return candidate.reaction.id

        return await self._run_batch(
            items=candidates,
            evaluate_fn=_evaluate_item,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            label="candidates",
        )

    # ── Shared pipeline helpers ──────────────────────────────────────

    async def _run_kegg_verification(
        self,
        reaction: Reaction,
        ext_ids: Any,
        evidence: ReactionEvidence,
    ) -> Any:
        """Run KEGG verification and extract match ratios (Steps 2-3)."""
        assert self._kegg is not None
        kegg_items = await self._kegg.check_evidence(
            reaction,
            kegg_reaction_ids=ext_ids.kegg_reaction_ids,
            model_substrates_kegg=ext_ids.kegg_substrate_ids,
            model_products_kegg=ext_ids.kegg_product_ids,
            ec_numbers=ext_ids.ec_numbers,
        )
        evidence.items.extend(kegg_items)

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

        return kegg_parsed_data

    async def _run_evidence_pipeline(
        self,
        reaction: Reaction,
        ext_ids: Any,
        evidence: ReactionEvidence,
        kegg_parsed_data: Any,
    ) -> None:
        """Run shared evidence sources: UniProt, PubMed, Gemini, Perplexity (Steps 5-8)."""
        # Step 5: UniProt verification
        if self._uniprot:
            try:
                uniprot_items = await self._uniprot.check_evidence(
                    reaction,
                    ec_numbers=ext_ids.ec_numbers,
                )
                evidence.items.extend(uniprot_items)
            except Exception as e:
                logger.warning("UniProt verification failed for %s: %s", reaction.id, e)

        # Step 6: PubMed verification
        if self._pubmed:
            try:
                pubmed_items = await self._pubmed.check_evidence(
                    reaction,
                    ec_numbers=ext_ids.ec_numbers,
                    organism_name=self._config.organism_name,
                )
                evidence.items.extend(pubmed_items)
            except Exception as e:
                logger.warning("PubMed verification failed for %s: %s", reaction.id, e)

        # Resolve metabolite names for LLM prompts
        reactant_names: dict[str, str] = {}
        product_names: dict[str, str] = {}
        for met_id in reaction.reactants:
            name = self._mapper.get_metabolite_name(met_id) if self._mapper else None
            reactant_names[met_id] = name or met_id
        for met_id in reaction.products:
            name = self._mapper.get_metabolite_name(met_id) if self._mapper else None
            product_names[met_id] = name or met_id

        # Step 8: Gemini verification (if KEGG match exists)
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

        # Step 9: Perplexity verification
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
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, item_id)

            tasks = [asyncio.create_task(_evaluate_with_limit(item)) for item in batch]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in task_results:
                if isinstance(result, Exception):
                    logger.warning("Batch subtask failed (%s): %s", label, result)

            logger.info("Evaluated %d/%d %s", completed, total, label)

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
