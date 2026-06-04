"""Evidence-based penalty calculation for gap-filling."""

from __future__ import annotations

import logging

from src.core.models import CandidateReaction, ReactionEvidence
from src.utils.config import Config
from src.utils.constants import GAPFILL_MAX_PENALTY

logger = logging.getLogger("metataskgapfill.gapfill.penalty")


class PenaltyCalculator:
    """Convert evidence scores to COBRApy gap-fill penalties.

    Higher evidence score -> lower penalty -> gap-filler preferentially selects.
    """

    def __init__(self, config: Config) -> None:
        self._epsilon = config.gapfill_penalty_epsilon  # 0.01
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
            base = 1.0 / (confidence_score + epsilon)
            if organism_exists is False: base *= org_mult
            elif organism_exists is None: base *= 3.0
            if no kegg_reaction_ids: base *= no_kegg_mult
            return min(base, max_penalty)
        """
        score = evidence.confidence_score if evidence else 0.0
        base = 1.0 / (score + self._epsilon)

        if candidate.organism_exists is False:
            base *= self._org_mult
        elif candidate.organism_exists is None:
            base *= 3.0

        if evidence is None or not evidence.kegg_reaction_ids:
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
                "Penalty for %s: %.2f (score=%.2f, org=%s)",
                rxn_id,
                penalty,
                evidence.confidence_score if evidence else 0.0,
                candidate.organism_exists,
            )
        return penalties
