"""KEGG-based GPR (Gene-Protein-Reaction) assignment."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import aiohttp

from src.api.rate_limiter import RateLimiter
from src.cache.cache_manager import CacheManager
from src.core.models import CandidateReaction, ReactionEvidence
from src.utils.constants import KEGG_API_BASE, ORGANISM_FILTER_CACHE_TTL

logger = logging.getLogger("metataskgapfill.gapfill.gpr")


class GPRAssigner:
    """Assign GPR rules to candidate reactions using KEGG orthology."""

    def __init__(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self._organism = organism_code
        self._cache = cache_manager
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(rate=3.0, burst=3)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _kegg_get(self, path: str) -> str | None:
        """Return KEGG text, empty text for 404, or None for a failed lookup."""
        await self._rate_limiter.acquire()
        url = f"{KEGG_API_BASE}/{path.lstrip('/')}"
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                if resp.status == 404:
                    return ""
                logger.warning("KEGG API returned %d for %s", resp.status, path)
                return None
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("KEGG request failed for %s: %s", path, e)
            return None

    def _parse_link_response(self, text: str) -> list[str]:
        """Parse KEGG /link response into list of target IDs.

        Response format: "source_id\\ttarget_id\\n" per line.
        Returns the target IDs (right column) with prefix stripped.
        """
        results: list[str] = []
        for line in text.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                target = parts[1].strip()
                # Strip prefix like "ko:", "eco:", "rn:" etc.
                if ":" in target:
                    target = target.split(":", 1)[1]
                results.append(target)
        return results

    async def _get_ko_ids(self, kegg_reaction_id: str) -> list[str]:
        """Get KEGG Orthology IDs for a reaction.

        GET /link/ko/rn:{reaction_id}
        """
        kegg_reaction_id = _extract_kegg_reaction_id(kegg_reaction_id)
        if not kegg_reaction_id:
            return []
        text = await self._kegg_get(f"link/ko/rn:{kegg_reaction_id}")
        if not text:
            return []
        return self._parse_link_response(text)

    async def _get_genes_for_ko(self, ko_id: str) -> list[str]:
        """Get organism-specific genes for a KO ID.

        GET /link/{organism}/ko:{ko_id}
        Uses cache with 30-day TTL.
        """
        # Legacy entries may contain temporary lookup failures cached as absence.
        cache_key = f"ko_genes:v2:{self._organism}:{ko_id}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if isinstance(cached, list):
                return [str(gene) for gene in cached]

        text = await self._kegg_get(f"link/{self._organism}/ko:{ko_id}")
        if text is None:
            # A temporary lookup failure must not become cached gene absence.
            return []
        genes: list[str] = []
        if text:
            genes = self._parse_link_response(text)

        if self._cache:
            await self._cache.set(cache_key, genes, ttl=ORGANISM_FILTER_CACHE_TTL)

        return genes

    async def assign_gpr(
        self,
        kegg_reaction_id: str,
        *,
        allowed_gene_ids: set[str] | None = None,
    ) -> tuple[str, list[str]]:
        """Assign GPR rule and gene list for a KEGG reaction.

        Returns:
            (gene_reaction_rule, [gene_ids])

        A reaction-to-KO link does not encode whether multiple KOs are subunits
        or alternative enzymes. Therefore a GPR is emitted only when exactly one
        KO group has matching organism genes. Multiple genes within that KO are
        treated as isozymes (OR). With multiple KO groups, genes are returned as
        provenance but no unsupported Boolean rule is invented.
        """
        ko_ids = await self._get_ko_ids(kegg_reaction_id)
        if not ko_ids:
            return ("", [])

        all_genes: list[str] = []
        ko_gene_groups: list[list[str]] = []

        for ko_id in ko_ids:
            genes = await self._get_genes_for_ko(ko_id)
            if allowed_gene_ids is not None:
                genes = [gene for gene in genes if gene in allowed_gene_ids]
            if genes:
                ko_gene_groups.append(genes)
                all_genes.extend(genes)

        if not ko_gene_groups:
            return ("", [])

        # A single KO can safely expose multiple matching organism genes as
        # alternative isozymes. Multiple KO links do not establish a complex.
        if len(ko_gene_groups) == 1:
            genes = ko_gene_groups[0]
            gpr = genes[0] if len(genes) == 1 else " or ".join(genes)
        else:
            logger.info(
                "Not assigning GPR for %s: %d KO groups do not establish complex stoichiometry",
                kegg_reaction_id,
                len(ko_gene_groups),
            )
            gpr = ""

        return (gpr, list(dict.fromkeys(all_genes)))

    async def assign_batch(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
        *,
        allowed_gene_ids: set[str] | None = None,
        evidence_results: dict[str, ReactionEvidence] | None = None,
    ) -> None:
        """Assign GPR rules to all candidates with KEGG reaction IDs.

        Modifies candidates in place: sets assigned_gpr and kegg_organism_genes.
        """
        total = len(candidates)
        for i, candidate in enumerate(candidates):
            evidence = (evidence_results or {}).get(candidate.reaction.id)
            kegg_ids = list(evidence.verified_kegg_reaction_ids) if evidence else []
            if evidence is None:
                kegg_ids = candidate.reaction.annotation.get(
                    "kegg.reaction", []
                ) or candidate.reaction.annotation.get("KEGG Reaction", [])

            if kegg_ids:
                # Use the first KEGG reaction ID
                kegg_id = _extract_kegg_reaction_id(kegg_ids[0])
                if not kegg_id:
                    continue
                gpr, genes = await self.assign_gpr(
                    kegg_id,
                    allowed_gene_ids=allowed_gene_ids,
                )
                candidate.assigned_gpr = gpr
                candidate.kegg_organism_genes = list(
                    dict.fromkeys(candidate.kegg_organism_genes + genes)
                )

            if progress_callback:
                progress_callback(i + 1, total, candidate.reaction.id)

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


def _extract_kegg_reaction_id(value: object) -> str:
    """Return bare ``Rxxxxx`` from KEGG IDs or identifiers.org URIs."""
    if not isinstance(value, str):
        return ""
    match = re.search(r"R\d{5}", value)
    return match.group(0) if match else value.strip()
