"""Confidence scoring algorithm for multi-source reaction evidence."""

from __future__ import annotations

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    ReactionEvidence,
)
from src.utils.constants import SOURCE_WEIGHTS


class ConfidenceScorer:
    """Calculate confidence scores from multi-source evidence.

    Supports KEGG, Gemini, and Perplexity sources with configurable weights.
    When a source is absent (no items), its weight is redistributed to
    sources that have evidence.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or dict(SOURCE_WEIGHTS)

    def score(self, evidence: ReactionEvidence) -> float:
        """Calculate overall confidence score from evidence items."""
        source_scores = self._compute_source_scores(evidence.items)

        # Store per-source scores
        evidence.kegg_score = source_scores.get(EvidenceSource.KEGG, 0.0)
        evidence.gemini_score = source_scores.get(EvidenceSource.GEMINI, 0.0)
        evidence.perplexity_score = source_scores.get(EvidenceSource.PERPLEXITY, 0.0)

        # Determine which sources have evidence
        active_sources: dict[str, float] = {}
        for source_key, weight in self._weights.items():
            try:
                source_enum = EvidenceSource(source_key)
            except ValueError:
                continue
            if source_enum in source_scores:
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
            total += source_scores[source_enum] * normalized_weight

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
