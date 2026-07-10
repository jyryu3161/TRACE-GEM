"""KEGG-based organism specificity filter for candidate reactions."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable

from src.api.base_client import APIUnavailableError, BaseAPIClient
from src.cache.cache_manager import CacheManager
from src.core.id_mapper import IdentifierMapper
from src.core.mapping_data import MappingData
from src.core.models import CandidateReaction
from src.utils.constants import (
    KEGG_API_BASE,
    ORGANISM_FILTER_CACHE_TTL,
    RATE_LIMITS,
)

logger = logging.getLogger("metataskgapfill.gapfill.organism_filter")


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
        self._reaction_genes: dict[str, list[str]] = {}
        self._lookup_failed = False
        self._organism_data_complete = False

        if mapping_data:
            self._id_mapper = IdentifierMapper(mapping_data)

    async def initialize(self) -> None:
        """Load the organism's complete reaction set from KEGG (1 API call).

        KEGG does not expose a direct organism -> reaction link endpoint.
        Build the set through organism KO/EC annotations and global KO/EC ->
        reaction links.
        """
        self._organism_reactions = await self._load_organism_reactions()
        self._organism_data_complete = bool(self._organism_reactions) and not self._lookup_failed
        logger.info(
            "Loaded %d KEGG reactions for organism '%s' (complete=%s)",
            len(self._organism_reactions),
            self._organism,
            self._organism_data_complete,
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
                candidate.organism_exists = found if found or self._organism_data_complete else None

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

    async def _get_organism_genes_for_reaction(self, kegg_reaction_id: str) -> list[str]:
        """Get organism-specific genes for a reaction.

        Genes are populated while loading the organism reaction set. KEGG's
        direct ``/link/{organism}/rn:Rxxxxx`` endpoint currently returns empty
        for this relationship.
        """
        cached_genes = self._reaction_genes.get(kegg_reaction_id)
        if cached_genes is not None:
            return list(cached_genes)

        cache_key = f"organism_genes:{self._organism}:{kegg_reaction_id}"
        data = await self._safe_kegg_get(
            f"/link/{self._organism}/rn:{kegg_reaction_id}",
            cache_key=cache_key,
            cache_ttl=ORGANISM_FILTER_CACHE_TTL,
        )

        if not data or not isinstance(data, str):
            return []

        # Parse: "rn:R00200\teco:b0001\n" -> ["b0001", ...]
        parsed_genes: list[str] = []
        for line in data.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                gene_part = parts[1]
                # Strip organism prefix: "eco:b0001" -> "b0001"
                gene_id = gene_part.split(":", 1)[1] if ":" in gene_part else gene_part
                if gene_id not in parsed_genes:
                    parsed_genes.append(gene_id)

        return parsed_genes

    async def close(self) -> None:
        """Close the KEGG client session."""
        await self._kegg_client.close()

    async def _safe_kegg_get(
        self,
        path: str,
        *,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
    ) -> dict | str | None:
        """KEGG GET that tolerates an unavailable service.

        Organism gene/reaction annotation is an optional enhancement to
        gap-fill, so an unreachable KEGG (open circuit, exhausted retries, or a
        4xx/5xx organism-link endpoint) degrades to "no organism data" rather
        than aborting the entire gap-fill run. This is deliberately different
        from the evidence path, where a KEGG outage is surfaced as an error.
        """
        try:
            return await self._kegg_client.get(path, cache_key=cache_key, cache_ttl=cache_ttl)
        except APIUnavailableError as exc:
            self._lookup_failed = True
            logger.warning("[organism_filter] KEGG unavailable for %s: %s", path, exc)
            return None

    async def _load_organism_reactions(self) -> set[str]:
        """Load organism-specific reactions via KEGG KO and EC links.

        KEGG supports organism -> KO/EC links and global KO/EC -> reaction
        links, but ``/link/reaction/{org}`` and ``/link/rn/{org}`` return 400.
        This method joins the supported link tables in memory and also builds
        a reaction -> organism genes map for GPR annotation.
        """
        ko_to_genes = await self._load_organism_feature_genes("ko")
        ec_to_genes = await self._load_organism_feature_genes("ec")

        reaction_genes: dict[str, set[str]] = defaultdict(set)
        reaction_ids: set[str] = set()

        if ko_to_genes:
            ko_to_reactions = await self._load_feature_reactions("ko")
            self._merge_feature_reactions(ko_to_genes, ko_to_reactions, reaction_genes)

        if ec_to_genes:
            ec_to_reactions = await self._load_feature_reactions("ec")
            self._merge_feature_reactions(ec_to_genes, ec_to_reactions, reaction_genes)

        for reaction_id, genes in reaction_genes.items():
            if genes:
                reaction_ids.add(reaction_id)

        self._reaction_genes = {
            reaction_id: sorted(genes) for reaction_id, genes in reaction_genes.items() if genes
        }

        if not reaction_ids:
            logger.warning("No KEGG reaction data for organism '%s'", self._organism)

        return reaction_ids

    async def _load_organism_feature_genes(
        self,
        feature_db: str,
    ) -> dict[str, set[str]]:
        """Return feature ID -> organism genes for KO or EC annotations."""
        cache_key = f"organism_{feature_db}:{self._organism}"
        data = await self._safe_kegg_get(
            f"/link/{feature_db}/{self._organism}",
            cache_key=cache_key,
            cache_ttl=ORGANISM_FILTER_CACHE_TTL,
        )
        return _parse_feature_gene_links(data, feature_db)

    async def _load_feature_reactions(self, feature_db: str) -> dict[str, set[str]]:
        """Return KO/EC feature ID -> KEGG reaction IDs."""
        cache_key = f"kegg_{feature_db}_reaction_links"
        data = await self._safe_kegg_get(
            f"/link/rn/{feature_db}",
            cache_key=cache_key,
            cache_ttl=ORGANISM_FILTER_CACHE_TTL,
        )
        return _parse_feature_reaction_links(data, feature_db)

    def _merge_feature_reactions(
        self,
        feature_to_genes: dict[str, set[str]],
        feature_to_reactions: dict[str, set[str]],
        reaction_genes: dict[str, set[str]],
    ) -> None:
        for feature_id, genes in feature_to_genes.items():
            for reaction_id in feature_to_reactions.get(feature_id, set()):
                reaction_genes[reaction_id].update(genes)


def _extract_id(uri: str) -> str:
    """Extract bare ID from URI or identifiers.org format."""
    if "/" in uri:
        return uri.rsplit("/", 1)[-1]
    return uri


def _parse_feature_gene_links(data: object, feature_db: str) -> dict[str, set[str]]:
    """Parse ``org:gene<TAB>{feature_db}:id`` KEGG link output."""
    result: dict[str, set[str]] = defaultdict(set)
    if not data or not isinstance(data, str):
        return result

    prefix = f"{feature_db}:"
    for line in data.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[1].startswith(prefix):
            continue
        gene = parts[0].split(":", 1)[-1]
        feature_id = parts[1].split(":", 1)[1]
        if gene and feature_id:
            result[feature_id].add(gene)
    return result


def _parse_feature_reaction_links(data: object, feature_db: str) -> dict[str, set[str]]:
    """Parse ``{feature_db}:id<TAB>rn:Rxxxxx`` KEGG link output."""
    result: dict[str, set[str]] = defaultdict(set)
    if not data or not isinstance(data, str):
        return result

    prefix = f"{feature_db}:"
    for line in data.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].startswith(prefix):
            continue
        feature_id = parts[0].split(":", 1)[1]
        match = re.search(r"rn:(R\d{5})", parts[1])
        if feature_id and match:
            result[feature_id].add(match.group(1))
    return result
