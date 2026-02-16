"""MetaCyc/BioCyc API client (optional, graceful degradation)."""

from __future__ import annotations

import logging

from src.api.base_client import BaseAPIClient
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)
from src.utils.constants import METACYC_API_BASE, RATE_LIMITS

logger = logging.getLogger("gem_evaluator.api.metacyc")


class MetaCycClient(BaseAPIClient):
    """Client for the BioCyc/MetaCyc web services.

    Note: MetaCyc has limited free API access. This client implements
    graceful degradation when the service is unavailable.
    """

    def __init__(self, cache_manager=None) -> None:
        super().__init__(
            name="metacyc",
            base_url=METACYC_API_BASE,
            rate=RATE_LIMITS["metacyc"],
            cache_manager=cache_manager,
        )

    async def get_reaction(self, metacyc_id: str) -> dict | str | None:
        """Get MetaCyc reaction entry."""
        return await self.get(
            "/apixml",
            params={"fn": "reactions", "id": f"META:{metacyc_id}", "detail": "low"},
            cache_key=f"metacyc:reaction:{metacyc_id}",
            cache_ttl=30 * 24 * 3600,
        )

    async def check_evidence(
        self,
        reaction: Reaction,
        metacyc_ids: list[str] | None = None,
        ec_numbers: list[str] | None = None,
        **kwargs,
    ) -> list[EvidenceItem]:
        """Check MetaCyc for reaction evidence."""
        mc_ids = metacyc_ids or []

        for mc_id in mc_ids:
            data = await self.get_reaction(mc_id)
            if data:
                # Check if experimental evidence exists
                data_str = str(data)
                has_exp = "EV-EXP" in data_str or "experimental" in data_str.lower()

                if has_exp:
                    strength = EvidenceStrength.STRONG
                    desc = f"MetaCyc reaction {mc_id} with experimental evidence"
                else:
                    strength = EvidenceStrength.MODERATE
                    desc = f"MetaCyc reaction {mc_id} documented"

                return [
                    EvidenceItem(
                        source=EvidenceSource.METACYC,
                        strength=strength,
                        description=desc,
                        url=f"https://metacyc.org/META/NEW-IMAGE?object={mc_id}",
                        raw_data={"metacyc_id": mc_id, "experimental": has_exp},
                    )
                ]

        # No MetaCyc IDs or lookup failed
        return [
            EvidenceItem(
                source=EvidenceSource.METACYC,
                strength=EvidenceStrength.ABSENT,
                description="No MetaCyc evidence found",
            )
        ]
