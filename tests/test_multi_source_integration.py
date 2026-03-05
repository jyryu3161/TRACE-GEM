"""Integration tests for multi-source evidence scoring."""

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
    """Test confidence scoring with the 7-source weight system."""

    @pytest.fixture
    def scorer(self) -> ConfidenceScorer:
        return ConfidenceScorer(dict(SOURCE_WEIGHTS))

    def test_all_seven_sources_strong(self, scorer: ConfidenceScorer) -> None:
        """All 7 sources return STRONG => score = 1.0."""
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
        """Only 2 sources have evidence => weights normalized to them."""
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
        # Both STRONG (1.0), normalized weights => score = 1.0
        assert score == pytest.approx(1.0)

    def test_mixed_strengths(self, scorer: ConfidenceScorer) -> None:
        """KEGG=STRONG, Gemini=MODERATE, Perplexity=WEAK => weighted average."""
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
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.MODERATE,
                description="Gemini moderate",
            )
        )
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.WEAK,
                description="Perplexity weak",
            )
        )
        score = scorer.score(ev)

        # Active: kegg(0.30), gemini(0.10), perplexity(0.10) => total=0.50
        # Normalized: kegg=0.60, gemini=0.20, perplexity=0.20
        # Score = 1.0*0.60 + 0.6*0.20 + 0.3*0.20 = 0.60 + 0.12 + 0.06 = 0.78
        assert 0.7 < score < 0.85

    def test_one_source_fails_others_succeed(self, scorer: ConfidenceScorer) -> None:
        """If one source has no evidence, its weight redistributes to others."""
        ev = ReactionEvidence(reaction_id="TEST")
        # Only KEGG and Perplexity, no Gemini
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG strong",
            )
        )
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.MODERATE,
                description="Perplexity moderate",
            )
        )
        score = scorer.score(ev)
        # kegg(0.30) + perplexity(0.10) => normalized: kegg=0.75, pplx=0.25
        # score = 1.0*0.75 + 0.6*0.25 = 0.75 + 0.15 = 0.90
        assert 0.85 < score < 0.95

    def test_all_sources_absent(self, scorer: ConfidenceScorer) -> None:
        """No evidence items => score = 0.0."""
        ev = ReactionEvidence(reaction_id="TEST")
        score = scorer.score(ev)
        assert score == 0.0

    def test_per_source_scores_stored(self, scorer: ConfidenceScorer) -> None:
        """Verify that per-source score attributes are set correctly."""
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
        ev.items.append(
            EvidenceItem(
                source=EvidenceSource.UNIPROT,
                strength=EvidenceStrength.WEAK,
                description="UniProt weak",
            )
        )
        scorer.score(ev)

        assert ev.kegg_score == pytest.approx(1.0)
        assert ev.bigg_score == pytest.approx(0.6)
        assert ev.uniprot_score == pytest.approx(0.3)
        assert ev.pubmed_score == 0.0
        assert ev.gemini_score == 0.0
        assert ev.perplexity_score == 0.0

    def test_score_breakdown_all_sources(self, scorer: ConfidenceScorer) -> None:
        """Score breakdown should include all 6 sources."""
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
