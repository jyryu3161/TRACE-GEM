"""Evidence-based penalty calculation for gap-filling."""

from __future__ import annotations

import logging

from src.core.models import CandidateReaction, EvidenceTier, ReactionEvidence
from src.utils.config import Config
from src.utils.constants import GAPFILL_MAX_PENALTY

logger = logging.getLogger("metataskgapfill.gapfill.penalty")


class PenaltyCalculator:
    """Convert categorical evidence tiers to COBRApy gap-fill penalties.

    Better evidence tier -> lower penalty -> gap-filler preferentially selects.
    The legacy numeric confidence score is no longer used as the primary
    penalty signal because the underlying 0.3/0.09 values are not biological
    probabilities.
    """

    _TIER_BASE_PENALTY = {
        EvidenceTier.HIGH: 1.0,
        EvidenceTier.MODERATE: 5.0,
        EvidenceTier.LOW: 25.0,
        # "Not assessable" (no KEGG anchor) is as costly as LOW; the no-KEGG
        # multiplier below then further penalizes the genuinely anchorless.
        EvidenceTier.NOT_ASSESSABLE: 25.0,
    }

    def __init__(self, config: Config) -> None:
        self._org_mult = config.gapfill_organism_penalty_multiplier  # 10.0
        self._no_kegg_mult = config.gapfill_no_kegg_penalty_multiplier  # 2.0
        self._max_penalty = GAPFILL_MAX_PENALTY  # 1000.0

    def calculate(
        self,
        candidate: CandidateReaction,
        evidence: ReactionEvidence | None,
    ) -> float:
        """Calculate penalty for a single candidate reaction.

        Formula:
            base = categorical tier penalty
            if organism_exists is False: base *= org_mult
            elif organism_exists is None: base *= 3.0
            if no kegg_reaction_ids: base *= no_kegg_mult
            return min(base, max_penalty)
        """
        tier = evidence.evidence_tier if evidence else EvidenceTier.NOT_ASSESSABLE
        base = self._TIER_BASE_PENALTY.get(tier, self._TIER_BASE_PENALTY[EvidenceTier.LOW])

        if candidate.organism_exists is False:
            base *= self._org_mult
        elif candidate.organism_exists is None:
            base *= 3.0

        # Penalize as no-KEGG unless a KEGG reaction was actually verified
        # (retrieved and non-contradictory). A rejected/annotated-only KEGG ID
        # must not launder into a lower penalty.
        if evidence is None or not evidence.verified_kegg_reaction_ids:
            base *= self._no_kegg_mult

        return min(base, self._max_penalty)

    def calculate_batch(
        self,
        candidates: list[CandidateReaction],
        evidence_results: dict[str, ReactionEvidence],
    ) -> dict[str, float]:
        """Calculate penalties for all candidates.

        Returns:
            {reaction_id: penalty} for cobra.flux_analysis.gapfill() penalties param.
        """
        penalties: dict[str, float] = {}
        for candidate in candidates:
            rxn_id = candidate.reaction.id
            evidence = evidence_results.get(rxn_id)
            penalty = self.calculate(candidate, evidence)
            penalties[rxn_id] = penalty
            logger.debug(
                "Penalty for %s: %.2f (tier=%s, legacy_score=%.2f, org=%s)",
                rxn_id,
                penalty,
                evidence.evidence_tier.value if evidence else EvidenceTier.LOW.value,
                evidence.confidence_score if evidence else 0.0,
                candidate.organism_exists,
            )
        return penalties
