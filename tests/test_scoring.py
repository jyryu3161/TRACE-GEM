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

    def test_custom_weights(self):
        weights = {"kegg": 0.5, "bigg": 0.5}
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
        assert score == pytest.approx(1.0)

    def test_two_source_scoring(self):
        weights = {"kegg": 0.70, "bigg": 0.30}
        scorer = ConfidenceScorer(weights)
        ev = ReactionEvidence(reaction_id="MULTI")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG found",
            ),
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.MODERATE,
                description="BiGG found",
            ),
        ]
        score = scorer.score(ev)
        assert score == pytest.approx(0.88)

    def test_weight_redistribution(self):
        weights = {"kegg": 0.70, "bigg": 0.30}
        scorer = ConfidenceScorer(weights)
        ev = ReactionEvidence(reaction_id="ONE")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.MODERATE,
                description="BiGG found",
            ),
        ]
        score = scorer.score(ev)
        assert score == pytest.approx(0.6)

    def test_per_source_scores(self, scorer):
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="Found",
            ),
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.WEAK,
                description="Found",
            ),
        ]
        scorer.score(ev)
        assert ev.kegg_score == 1.0
        assert ev.bigg_score == 0.3

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
        assert set(breakdown) == {"kegg", "bigg"}
        assert breakdown["kegg"]["raw_score"] == 1.0
        assert breakdown["bigg"]["raw_score"] == 0.0

    def test_best_strength_wins(self, scorer):
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
        assert ev.bigg_score == 0.0
