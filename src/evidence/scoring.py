"""Confidence scoring algorithm for multi-source reaction evidence."""

from __future__ import annotations

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
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

    def score(self, evidence: ReactionEvidence) -> float:
        """Calculate overall confidence score from evidence items."""
        source_scores = self._compute_source_scores(evidence.items)

        # Store per-source scores
        evidence.kegg_score = source_scores.get(EvidenceSource.KEGG, 0.0)
        evidence.bigg_score = source_scores.get(EvidenceSource.BIGG, 0.0)
        evidence.evidence_tier, evidence.evidence_rationale = self._classify_tier(
            source_scores
        )

        # Score all configured sources. Missing or ABSENT source evidence is
        # treated as a zero for that source, not redistributed to other sources.
        active_sources: dict[str, float] = {}
        for source_key, weight in self._weights.items():
            try:
                EvidenceSource(source_key)
            except ValueError:
                continue
            if weight > 0:
                active_sources[source_key] = weight

        # If no active sources, score is 0
        if not active_sources:
            evidence.confidence_score = 0.0
            return 0.0

        # Normalize weights for active sources only
        total_weight = sum(active_sources.values())
        if total_weight <= 0:
            evidence.confidence_score = 0.0
            return 0.0

        total = 0.0
        for source_key, weight in active_sources.items():
            source_enum = EvidenceSource(source_key)
            normalized_weight = weight / total_weight
            total += source_scores.get(source_enum, 0.0) * normalized_weight

        # Clamp to [0, 1]
        evidence.confidence_score = max(0.0, min(1.0, total))
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

    def _classify_tier(
        self,
        source_scores: dict[EvidenceSource, float],
    ) -> tuple[EvidenceTier, str]:
        """Classify evidence into High/Moderate/Low with KEGG as the primary source."""
        kegg = source_scores.get(EvidenceSource.KEGG, EvidenceStrength.ABSENT.value)
        bigg = source_scores.get(EvidenceSource.BIGG, EvidenceStrength.ABSENT.value)

        if kegg >= EvidenceStrength.MODERATE.value:
            return (
                EvidenceTier.HIGH,
                "KEGG reaction evidence is present for this reaction.",
            )

        if kegg > EvidenceStrength.ABSENT.value:
            return (
                EvidenceTier.MODERATE,
                "KEGG evidence is weak or partial; treat as plausible but not high-confidence.",
            )

        if bigg >= EvidenceStrength.STRONG.value:
            return (
                EvidenceTier.MODERATE,
                "No KEGG reaction evidence was confirmed, but BiGG prevalence is strong.",
            )

        return (
            EvidenceTier.LOW,
            "No confirmed KEGG evidence and BiGG support is weak or absent.",
        )

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
