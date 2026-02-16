"""BiGG Models API client."""

from __future__ import annotations

import logging

from src.api.base_client import BaseAPIClient
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)
from src.utils.constants import BIGG_API_BASE, RATE_LIMITS

logger = logging.getLogger("gem_evaluator.api.bigg")


class BiGGClient(BaseAPIClient):
    """Client for the BiGG Models database REST API v2."""

    def __init__(self, cache_manager=None) -> None:
        super().__init__(
            name="bigg",
            base_url=BIGG_API_BASE,
            rate=RATE_LIMITS["bigg"],
            cache_manager=cache_manager,
        )

    async def get_reaction(self, bigg_id: str) -> dict | str | None:
        """Get reaction details including cross-references."""
        return await self.get(
            f"/universal/reactions/{bigg_id}",
            cache_key=f"bigg:reaction:{bigg_id}",
            cache_ttl=30 * 24 * 3600,
        )

    async def get_metabolite(self, bigg_id: str) -> dict | str | None:
        """Get metabolite details."""
        return await self.get(
            f"/universal/metabolites/{bigg_id}",
            cache_key=f"bigg:metabolite:{bigg_id}",
            cache_ttl=30 * 24 * 3600,
        )

    async def search_reactions(self, query: str) -> dict | str | None:
        """Search for reactions by name or ID."""
        return await self.get(
            "/search",
            params={"query": query, "search_type": "reactions"},
            cache_key=f"bigg:search:rxn:{query}",
        )

    async def check_evidence(
        self, reaction: Reaction, bigg_id: str | None = None, **kwargs
    ) -> list[EvidenceItem]:
        """Check BiGG for evidence of reaction existence."""
        rid = bigg_id or reaction.id
        data = await self.get_reaction(rid)
        if data is None:
            return [
                EvidenceItem(
                    source=EvidenceSource.BIGG,
                    strength=EvidenceStrength.ABSENT,
                    description=f"Reaction '{rid}' not found in BiGG database",
                )
            ]

        if not isinstance(data, dict):
            return [
                EvidenceItem(
                    source=EvidenceSource.BIGG,
                    strength=EvidenceStrength.WEAK,
                    description=f"Reaction '{rid}' returned non-JSON data from BiGG",
                )
            ]

        models = data.get("models_containing_reaction", [])
        model_count = len(models)

        if model_count > 5:
            strength = EvidenceStrength.STRONG
            desc = f"Found in {model_count} BiGG models"
        elif model_count >= 2:
            strength = EvidenceStrength.MODERATE
            desc = f"Found in {model_count} BiGG models"
        elif model_count == 1:
            strength = EvidenceStrength.WEAK
            desc = f"Found in 1 BiGG model: {models[0].get('bigg_id', '?')}"
        else:
            strength = EvidenceStrength.WEAK
            desc = "Reaction exists in BiGG universal but not in any specific model"

        model_names = [m.get("bigg_id", "") for m in models[:10]]
        url = f"http://bigg.ucsd.edu/universal/reactions/{rid}"

        return [
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=strength,
                description=desc,
                url=url,
                raw_data={
                    "model_count": model_count,
                    "models": model_names,
                    "database_links": data.get("database_links", {}),
                },
            )
        ]
