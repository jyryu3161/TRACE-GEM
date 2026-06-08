"""Integration tests for KEGG/BiGG evidence scoring."""

from __future__ import annotations

import pytest

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    ReactionEvidence,
)
from src.evidence.scoring import ConfidenceScorer
from src.utils.constants import SOURCE_WEIGHTS


class TestMultiSourceScoring:
    """Test confidence scoring with the KEGG/BiGG weight system."""

    @pytest.fixture
    def scorer(self) -> ConfidenceScorer:
        return ConfidenceScorer(dict(SOURCE_WEIGHTS))

    def test_all_sources_strong(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        for source in EvidenceSource:
            ev.items.append(
                EvidenceItem(
                    source=source,
                    strength=EvidenceStrength.STRONG,
                    description=f"{source.value} strong",
                )
            )
        score = scorer.score(ev)
        assert score == pytest.approx(1.0)

    def test_weight_redistribution_two_sources(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG strong",
            )
        )
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.STRONG,
                description="BiGG strong",
            )
        )
        score = scorer.score(ev)
        assert score == pytest.approx(1.0)

    def test_mixed_strengths(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG strong",
            )
        )
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.MODERATE,
                description="BiGG moderate",
            )
        )
        score = scorer.score(ev)
        assert score == pytest.approx(0.88)

    def test_one_source_fails_others_succeed(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG strong",
            )
        )
        score = scorer.score(ev)
        assert score == pytest.approx(0.7)

    def test_all_sources_absent(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        score = scorer.score(ev)
        assert score == 0.0

    def test_per_source_scores_stored(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG strong",
            )
        )
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.MODERATE,
                description="BiGG moderate",
            )
        )
        scorer.score(ev)

        assert ev.kegg_score == pytest.approx(1.0)
        assert ev.bigg_score == pytest.approx(0.6)

    def test_score_breakdown_all_sources(self, scorer: ConfidenceScorer) -> None:
        ev = ReactionEvidence(reaction_id="TEST")
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="test",
            )
        )
        scorer.score(ev)
        breakdown = scorer.score_breakdown(ev)
        assert set(breakdown.keys()) == {s.value for s in EvidenceSource}
