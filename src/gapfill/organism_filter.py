"""KEGG-based organism specificity filter for candidate reactions."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from src.api.base_client import BaseAPIClient
from src.api.rate_limiter import RateLimiter
from src.cache.cache_manager import CacheManager
from src.core.id_mapper import IdentifierMapper
from src.core.mapping_data import MappingData
from src.core.models import CandidateReaction, ExternalIDs
from src.utils.constants import (
    KEGG_API_BASE,
    ORGANISM_FILTER_CACHE_TTL,
    RATE_LIMITS,
)

logger = logging.getLogger("gem_evaluator.gapfill.organism_filter")


class _KEGGLinkClient(BaseAPIClient):
    """Minimal KEGG client for link/list queries (not reaction verification)."""

    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        super().__init__(
            name="kegg_link",
            base_url=KEGG_API_BASE,
            rate=RATE_LIMITS["kegg"],
            cache_manager=cache_manager,
        )

    async def check_evidence(self, reaction, **kwargs):
        """Not used -- required by ABC."""
        return []


class OrganismFilter:
    """Filter candidate reactions by organism specificity using KEGG.

    Optimization: loads ALL organism reactions in one API call, then does
    in-memory set lookups for each candidate (O(1) per candidate).
    """

    def __init__(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
        mapping_data: MappingData | None = None,
    ) -> None:
        self._organism = organism_code
        self._cache = cache_manager
        self._mapping = mapping_data
        self._id_mapper: IdentifierMapper | None = None
        self._kegg_client = _KEGGLinkClient(cache_manager=cache_manager)
        self._organism_reactions: set[str] | None = None

        if mapping_data:
            self._id_mapper = IdentifierMapper(mapping_data)

    async def initialize(self) -> None:
        """Load the organism's complete reaction set from KEGG (1 API call).

        GET https://rest.kegg.jp/link/reaction/{organism_code}
        Response format: "eco:b0001\\trn:R00200\\n"
        """
        self._organism_reactions = await self._load_organism_reactions()
        logger.info(
            "Loaded %d KEGG reactions for organism '%s'",
            len(self._organism_reactions),
            self._organism,
        )

    async def filter_candidates(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[CandidateReaction]:
        """Determine organism specificity for each candidate.

        Sets candidate.organism_exists and candidate.kegg_organism_genes.
        """
        if self._organism_reactions is None:
            await self.initialize()

        assert self._organism_reactions is not None

        for i, candidate in enumerate(candidates):
            kegg_ids = self._resolve_kegg_ids(candidate)

            if not kegg_ids:
                candidate.organism_exists = None
            else:
                found = False
                for kid in kegg_ids:
                    if kid in self._organism_reactions:
                        found = True
                        genes = await self._get_organism_genes_for_reaction(kid)
                        candidate.kegg_organism_genes.extend(genes)
                        break
                candidate.organism_exists = found

            if progress_callback:
                progress_callback(i + 1, len(candidates), candidate.reaction.id)

        exists_count = sum(1 for c in candidates if c.organism_exists is True)
        absent_count = sum(1 for c in candidates if c.organism_exists is False)
        unknown_count = sum(1 for c in candidates if c.organism_exists is None)
        logger.info(
            "Organism filter: %d exist, %d absent, %d unknown (no KEGG ID)",
            exists_count,
            absent_count,
            unknown_count,
        )

        return candidates

    def _resolve_kegg_ids(self, candidate: CandidateReaction) -> list[str]:
        """Resolve KEGG reaction IDs for a candidate via multiple strategies.

        1. Direct annotation ("KEGG Reaction")
        2. BiGG ID -> mapping
        3. EC Number -> mapping
        """
        kegg_ids: list[str] = []
        rxn = candidate.reaction
        ann = rxn.annotation

        # 1. Direct from annotation
        for key in ("KEGG Reaction", "kegg.reaction"):
            if key in ann:
                for val in ann[key]:
                    kid = _extract_id(val)
                    if kid and kid not in kegg_ids:
                        kegg_ids.append(kid)

        if kegg_ids:
            return kegg_ids

        # 2. BiGG ID -> KEGG via mapping
        if self._mapping:
            bigg_id = rxn.id
            if bigg_id.startswith("R_"):
                bigg_id = bigg_id[2:]
            mapped = self._mapping.rxn_bigg_to_kegg.get(bigg_id, [])
            for kid in mapped:
                if kid not in kegg_ids:
                    kegg_ids.append(kid)

        if kegg_ids:
            return kegg_ids

        # 3. EC Number -> KEGG via mapping
        if self._mapping:
            for key in ("EC Number", "ec-code", "ec_number"):
                if key in ann:
                    for val in ann[key]:
                        ec = _extract_id(val)
                        ec_kegg = self._mapping.rxn_ec_to_kegg.get(ec, [])
                        for kid in ec_kegg:
                            if kid not in kegg_ids:
                                kegg_ids.append(kid)

        return kegg_ids

    async def _load_organism_reactions(self) -> set[str]:
        """Load all reaction IDs for the organism from KEGG.

        Cache key: "organism_reactions:{code}"
        Cache TTL: 30 days
        """
        cache_key = f"organism_reactions:{self._organism}"
        data = await self._kegg_client.get(
            f"/link/reaction/{self._organism}",
            cache_key=cache_key,
            cache_ttl=ORGANISM_FILTER_CACHE_TTL,
        )

        if not data or not isinstance(data, str):
            logger.warning(
                "No KEGG reaction data for organism '%s'", self._organism
            )
            return set()

        # Parse: "eco:b0001\trn:R00200\n" -> {"R00200", ...}
        reaction_ids: set[str] = set()
        for line in data.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                match = re.search(r"rn:(R\d{5})", parts[1])
                if match:
                    reaction_ids.add(match.group(1))

        return reaction_ids

    async def _get_organism_genes_for_reaction(
        self, kegg_reaction_id: str
    ) -> list[str]:
        """Get organism-specific genes for a reaction.

        GET /link/genes/{organism}/rn:{reaction_id}
        """
        cache_key = f"organism_genes:{self._organism}:{kegg_reaction_id}"
        data = await self._kegg_client.get(
            f"/link/{self._organism}/rn:{kegg_reaction_id}",
            cache_key=cache_key,
            cache_ttl=ORGANISM_FILTER_CACHE_TTL,
        )

        if not data or not isinstance(data, str):
            return []

        # Parse: "rn:R00200\teco:b0001\n" -> ["b0001", ...]
        genes: list[str] = []
        for line in data.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                gene_part = parts[1]
                # Strip organism prefix: "eco:b0001" -> "b0001"
                if ":" in gene_part:
                    gene_id = gene_part.split(":", 1)[1]
                else:
                    gene_id = gene_part
                if gene_id not in genes:
                    genes.append(gene_id)

        return genes

    async def close(self) -> None:
        """Close the KEGG client session."""
        await self._kegg_client.close()


def _extract_id(uri: str) -> str:
    """Extract bare ID from URI or identifiers.org format."""
    if "/" in uri:
        return uri.rsplit("/", 1)[-1]
    return uri
