"""Evidence-based penalty calculation for gap-filling."""

from __future__ import annotations

import logging

from src.core.models import CandidateReaction, EvidenceTier, ReactionEvidence
from src.utils.config import Config

logger = logging.getLogger("metataskgapfill.gapfill.penalty")


class PenaltyCalculator:
    """Convert categorical evidence tiers to COBRApy gap-fill penalties.

    Better evidence tier -> lower penalty -> gap-filler preferentially selects.
    The legacy numeric confidence score is no longer used as the primary
    penalty signal because the underlying 0.3/0.09 values are not biological
    probabilities.
    """

    def __init__(self, config: Config) -> None:
        self._tier_base_penalty = {
            EvidenceTier.HIGH: config.gapfill_penalty_high,
            EvidenceTier.MODERATE: config.gapfill_penalty_moderate,
            EvidenceTier.LOW: config.gapfill_penalty_low,
            EvidenceTier.NOT_ASSESSABLE: config.gapfill_penalty_not_assessable,
        }
        self._org_mult = config.gapfill_organism_penalty_multiplier
        self._org_unknown_mult = config.gapfill_organism_unknown_multiplier
        self._no_kegg_mult = config.gapfill_no_kegg_penalty_multiplier
        self._max_penalty = config.gapfill_max_penalty

    def calculate(
        self,
        candidate: CandidateReaction,
        evidence: ReactionEvidence | None,
    ) -> float:
        """Calculate penalty for a single candidate reaction.

        Formula:
            base = categorical tier penalty
            if organism_exists is False: base *= org_mult
            elif organism_exists is None: base *= configured unknown multiplier
            if no kegg_reaction_ids: base *= no_kegg_mult
            return min(base, max_penalty)
        """
        tier = evidence.evidence_tier if evidence else EvidenceTier.NOT_ASSESSABLE
        base = self._tier_base_penalty.get(tier, self._tier_base_penalty[EvidenceTier.LOW])

        if candidate.organism_exists is False:
            base *= self._org_mult
        elif candidate.organism_exists is None:
            base *= self._org_unknown_mult

        # Penalize as no-KEGG unless a KEGG reaction was actually verified
        # (retrieved and non-contradictory). A rejected/annotated-only KEGG ID
        # must not launder into a lower penalty.
        if evidence is None or not evidence.verified_kegg_reaction_ids:
            base *= self._no_kegg_mult

        return min(base, self._max_penalty)

    def parameters(self) -> dict[str, object]:
        """Return the exact optimization-cost policy for provenance exports."""
        return {
            "tier_base_penalty": {
                tier.value: value for tier, value in self._tier_base_penalty.items()
            },
            "organism_absent_multiplier": self._org_mult,
            "organism_unknown_multiplier": self._org_unknown_mult,
            "missing_verified_kegg_multiplier": self._no_kegg_mult,
            "maximum_penalty": self._max_penalty,
        }

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
