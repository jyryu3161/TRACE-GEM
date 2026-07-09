"""Confidence scoring algorithm for multi-source reaction evidence."""

from __future__ import annotations

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceTier,
    ReactionEvidence,
)
from src.utils.constants import SOURCE_WEIGHTS


class ConfidenceScorer:
    """Calculate evidence confidence and categorical tiers.

    Supports KEGG and BiGG sources with configurable weights. Enabled sources
    keep their configured weights even when a source is absent, so a strong
    BiGG match cannot become 1.0 if KEGG verification failed or found no match.

    The numeric ``confidence_score`` is retained as a legacy ordering/export
    field. User-facing decisions should use ``evidence_tier``.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or dict(SOURCE_WEIGHTS)

    # Tier → legacy numeric confidence_score (ordering/export only; the tier is
    # the authoritative categorical decision).
    _TIER_SCORE = {
        EvidenceTier.HIGH: 1.0,
        EvidenceTier.MODERATE: 0.6,
        EvidenceTier.LOW: 0.3,
        EvidenceTier.NOT_ASSESSABLE: 0.0,
    }

    def score(self, evidence: ReactionEvidence) -> float:
        """Classify the reaction's KEGG-only evidence tier and derive a score.

        The tier is decided by rule from the KEGG provenance states already set
        on ``evidence`` (kegg_anchored / reconciliation_state /
        ec_concordance_state). ``kegg_score`` is retained for display; BiGG is
        no longer an evidence source. ``confidence_score`` is a monotone function
        of the tier, kept only for legacy ordering/export.
        """
        source_scores = self._compute_source_scores(evidence.items)
        evidence.kegg_score = source_scores.get(EvidenceSource.KEGG, 0.0)
        evidence.bigg_score = 0.0  # BiGG removed from evidence scoring

        evidence.evidence_tier, evidence.evidence_rationale = self._classify_tier(evidence)
        evidence.confidence_score = self._TIER_SCORE[evidence.evidence_tier]
        return evidence.confidence_score

    def _compute_source_scores(self, items: list[EvidenceItem]) -> dict[EvidenceSource, float]:
        """Compute the best score per source from evidence items."""
        scores: dict[EvidenceSource, float] = {}

        for item in items:
            val = item.strength.value
            current = scores.get(item.source, 0.0)
            if val > current:
                scores[item.source] = val

        return scores

    # Rule-based KEGG-only tier decision. Keys are (reconciliation_state,
    # ec_concordance_state). Conservative by construction: metabolite
    # contradiction is always Low, EC discordance never yields High, and a KEGG
    # ID with nothing corroborating it (unverifiable + unknown EC) is Low.
    _TIER_TABLE = {
        ("full", "concordant"): EvidenceTier.HIGH,
        ("full", "unknown"): EvidenceTier.HIGH,
        ("full", "discordant"): EvidenceTier.MODERATE,
        ("partial", "concordant"): EvidenceTier.MODERATE,
        ("partial", "unknown"): EvidenceTier.MODERATE,
        ("partial", "discordant"): EvidenceTier.LOW,
        ("unverifiable", "concordant"): EvidenceTier.MODERATE,
        ("unverifiable", "unknown"): EvidenceTier.LOW,
        ("unverifiable", "discordant"): EvidenceTier.LOW,
        ("none_contradictory", "concordant"): EvidenceTier.LOW,
        ("none_contradictory", "unknown"): EvidenceTier.LOW,
        ("none_contradictory", "discordant"): EvidenceTier.LOW,
    }

    def _classify_tier(self, evidence: ReactionEvidence) -> tuple[EvidenceTier, str]:
        """Classify the KEGG-only evidence tier from provenance states."""
        if not evidence.kegg_anchored:
            return (
                EvidenceTier.NOT_ASSESSABLE,
                "No KEGG reaction could be linked to this reaction; "
                "its identity could not be assessed.",
            )

        recon = evidence.reconciliation_state
        ec = evidence.ec_concordance_state
        tier = self._TIER_TABLE.get((recon, ec), EvidenceTier.LOW)

        recon_txt = recon.replace("_", " ")
        if tier is EvidenceTier.HIGH:
            rationale = (
                f"KEGG reaction identity corroborated (metabolite reconciliation: {recon_txt}"
                + (", EC concordant)." if ec == "concordant" else ").")
            )
        elif tier is EvidenceTier.MODERATE:
            rationale = (
                f"KEGG-anchored with partial/consistent support (metabolites: {recon_txt}, "
                f"EC: {ec}); plausible but not fully reconciled."
            )
        else:  # LOW
            if recon == "none_contradictory":
                rationale = "KEGG entry found but its metabolites contradict the model reaction."
            else:
                rationale = (
                    f"KEGG-anchored but unsupported (metabolites: {recon_txt}, EC: {ec})."
                )
        return (tier, rationale)

    def score_breakdown(self, evidence: ReactionEvidence) -> dict[str, dict]:
        """Return detailed scoring breakdown for display."""
        source_scores = self._compute_source_scores(evidence.items)

        breakdown = {}
        for source in EvidenceSource:
            score = source_scores.get(source, 0.0)
            weight = self._weights.get(source.value, 0.0)
            weighted = weight * score
            breakdown[source.value] = {
                "raw_score": score,
                "weight": weight,
                "weighted_score": weighted,
                "evidence_tier": evidence.evidence_tier.value,
                "evidence_rationale": evidence.evidence_rationale,
                "items": [
                    {
                        "strength": item.strength.name,
                        "description": item.description,
                        "url": item.url,
                    }
                    for item in evidence.items
                    if item.source == source
                ],
            }

        return breakdown
