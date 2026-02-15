"""Tests for confidence scoring algorithm."""

import pytest

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    ReactionEvidence,
)
from src.evidence.scoring import ConfidenceScorer


class TestConfidenceScorer:
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()

    def test_strong_kegg_only(self, scorer):
        """KEGG-only evidence: weight normalized to 1.0."""
        ev = ReactionEvidence(reaction_id="ENO")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG reaction R00658",
            ),
        ]
        score = scorer.score(ev)
        # KEGG STRONG=1.0, only source → normalized weight=1.0 → score=1.0
        assert score == pytest.approx(1.0)

    def test_all_absent(self, scorer):
        ev = ReactionEvidence(reaction_id="FAKE")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.ABSENT,
                description="No KEGG reaction found",
            ),
        ]
        score = scorer.score(ev)
        assert score == 0.0

    def test_moderate_evidence(self, scorer):
        ev = ReactionEvidence(reaction_id="PARTIAL")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.MODERATE,
                description="Partial match",
            ),
        ]
        score = scorer.score(ev)
        # Only KEGG → normalized weight=1.0 → MODERATE=0.6
        assert score == pytest.approx(0.6)

    def test_weak_evidence(self, scorer):
        ev = ReactionEvidence(reaction_id="WEAK")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.WEAK,
                description="Low match",
            ),
        ]
        score = scorer.score(ev)
        assert score == pytest.approx(0.3)

    def test_score_clamped(self, scorer):
        ev = ReactionEvidence(reaction_id="OVER")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
        ]
        score = scorer.score(ev)
        assert score <= 1.0

    def test_custom_weights(self):
        weights = {"kegg": 0.5, "gemini": 0.3, "perplexity": 0.2}
        scorer = ConfidenceScorer(weights)
        ev = ReactionEvidence(reaction_id="CUSTOM")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
        ]
        score = scorer.score(ev)
        # Only KEGG active → normalized to 1.0 → STRONG=1.0
        assert score == pytest.approx(1.0)

    def test_multi_source_scoring(self):
        """Three sources with different strengths."""
        weights = {"kegg": 0.50, "gemini": 0.25, "perplexity": 0.25}
        scorer = ConfidenceScorer(weights)
        ev = ReactionEvidence(reaction_id="MULTI")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG found",
            ),
            EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.STRONG,
                description="Gemini match",
            ),
            EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.MODERATE,
                description="Perplexity partial",
            ),
        ]
        score = scorer.score(ev)
        # All 3 active, total_weight = 1.0
        # KEGG: 1.0 * 0.5 + Gemini: 1.0 * 0.25 + Perplexity: 0.6 * 0.25 = 0.9
        assert score == pytest.approx(0.9)

    def test_two_source_weight_redistribution(self):
        """When one source is missing, weights redistribute."""
        weights = {"kegg": 0.50, "gemini": 0.25, "perplexity": 0.25}
        scorer = ConfidenceScorer(weights)
        ev = ReactionEvidence(reaction_id="TWO")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
            EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.STRONG,
                description="Match",
            ),
        ]
        score = scorer.score(ev)
        # KEGG + Gemini active, total_weight = 0.75
        # KEGG: 1.0 * (0.5/0.75) + Gemini: 1.0 * (0.25/0.75) = 1.0
        assert score == pytest.approx(1.0)

    def test_per_source_scores(self, scorer):
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
        ]
        scorer.score(ev)
        assert ev.kegg_score == 1.0
        assert ev.gemini_score == 0.0
        assert ev.perplexity_score == 0.0

    def test_per_source_scores_multi(self):
        scorer = ConfidenceScorer()
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
            EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.MODERATE,
                description="Match",
            ),
            EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.WEAK,
                description="Uncertain",
            ),
        ]
        scorer.score(ev)
        assert ev.kegg_score == 1.0
        assert ev.gemini_score == 0.6
        assert ev.perplexity_score == 0.3

    def test_score_breakdown(self, scorer):
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
        ]
        scorer.score(ev)
        breakdown = scorer.score_breakdown(ev)
        assert "kegg" in breakdown
        assert "gemini" in breakdown
        assert "perplexity" in breakdown
        assert breakdown["kegg"]["raw_score"] == 1.0

    def test_best_strength_wins(self, scorer):
        """When multiple KEGG items exist, best strength is used."""
        ev = ReactionEvidence(reaction_id="MULTI")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.WEAK,
                description="Weak match via EC",
            ),
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Strong match via direct ID",
            ),
        ]
        score = scorer.score(ev)
        assert score == pytest.approx(1.0)

    def test_no_items(self, scorer):
        ev = ReactionEvidence(reaction_id="EMPTY")
        score = scorer.score(ev)
        assert score == 0.0
        assert ev.kegg_score == 0.0
        assert ev.gemini_score == 0.0
        assert ev.perplexity_score == 0.0
