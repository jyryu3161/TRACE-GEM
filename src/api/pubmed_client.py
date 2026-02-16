"""PubMed/NCBI Entrez API client."""

from __future__ import annotations

import logging

from src.api.base_client import BaseAPIClient
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)
from src.utils.constants import PUBMED_API_BASE, RATE_LIMITS

logger = logging.getLogger("gem_evaluator.api.pubmed")


class PubMedClient(BaseAPIClient):
    """Client for PubMed/NCBI E-utilities API."""

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        cache_manager=None,
    ) -> None:
        rate = RATE_LIMITS["pubmed_with_key"] if api_key else RATE_LIMITS["pubmed_no_key"]
        super().__init__(
            name="pubmed",
            base_url=PUBMED_API_BASE,
            rate=rate,
            cache_manager=cache_manager,
        )
        self._email = email or "gem_evaluator@example.com"
        self._api_key = api_key

    def _base_params(self) -> dict:
        params = {"email": self._email, "retmode": "json"}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    async def search(self, query: str, max_results: int = 20) -> dict | str | None:
        """Search PubMed for articles matching query."""
        params = self._base_params()
        params.update(
            {
                "db": "pubmed",
                "term": query,
                "retmax": str(max_results),
                "sort": "relevance",
            }
        )
        return await self.get(
            "/esearch.fcgi",
            params=params,
            cache_key=f"pubmed:search:{query}:{max_results}",
            cache_ttl=24 * 3600,
        )

    async def check_evidence(
        self,
        reaction: Reaction,
        ec_numbers: list[str] | None = None,
        organism_name: str | None = None,
        **kwargs,
    ) -> list[EvidenceItem]:
        """Search PubMed for literature evidence of this reaction."""
        queries = self._build_queries(reaction, ec_numbers, organism_name)

        best_count = 0
        best_query = ""

        for query in queries:
            data = await self.search(query, max_results=20)
            if data and isinstance(data, dict):
                esearch = data.get("esearchresult", {})
                count = int(esearch.get("count", 0))
                if count > best_count:
                    best_count = count
                    best_query = query
                # If we found good results, no need to try more queries
                if count >= 3:
                    break

        if best_count > 10:
            strength = EvidenceStrength.STRONG
        elif best_count >= 3:
            strength = EvidenceStrength.MODERATE
        elif best_count >= 1:
            strength = EvidenceStrength.WEAK
        else:
            strength = EvidenceStrength.ABSENT

        desc = (
            f"{best_count} PubMed article(s) found"
            if best_count > 0
            else "No PubMed articles found"
        )

        url = (
            f"https://pubmed.ncbi.nlm.nih.gov/?term={best_query.replace(' ', '+')}"
            if best_query
            else None
        )

        return [
            EvidenceItem(
                source=EvidenceSource.PUBMED,
                strength=strength,
                description=desc,
                url=url,
                raw_data={"count": best_count, "query": best_query},
            )
        ]

    def _build_queries(
        self,
        reaction: Reaction,
        ec_numbers: list[str] | None,
        organism_name: str | None,
    ) -> list[str]:
        """Build PubMed search queries from reaction info, most specific first."""
        queries = []
        org = organism_name or ""

        # Most specific: reaction name + organism
        if reaction.name and org:
            queries.append(f'"{reaction.name}" AND "{org}"')

        # EC number + organism
        if ec_numbers:
            for ec in ec_numbers[:2]:
                if org:
                    queries.append(f'"EC {ec}" AND "{org}"')
                queries.append(f'"EC {ec}" AND enzyme')

        # Reaction name alone
        if reaction.name:
            clean_name = reaction.name.replace("'", "").replace('"', "")
            queries.append(f'"{clean_name}" AND enzyme')

        return queries[:4]  # Max 4 queries to limit API calls
