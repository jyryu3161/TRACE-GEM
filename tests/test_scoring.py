"""Tests for the rule-based, KEGG-only confidence scorer.

The tier is decided from the KEGG provenance states set on the evidence
(kegg_anchored / reconciliation_state / ec_concordance_state), not from a
blended numeric score. BiGG is no longer an evidence source.
"""

import pytest

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    EvidenceTier,
    ReactionEvidence,
)
from src.evidence.scoring import ConfidenceScorer


def _ev(anchored: bool, recon: str, ec: str) -> ReactionEvidence:
    ev = ReactionEvidence(reaction_id="R")
    ev.kegg_anchored = anchored
    ev.reconciliation_state = recon
    ev.ec_concordance_state = ec
    return ev


class TestRuleBasedTiers:
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()

    def test_not_anchored_is_not_assessable(self, scorer):
        ev = _ev(False, "unverifiable", "unknown")
        score = scorer.score(ev)
        assert ev.evidence_tier == EvidenceTier.NOT_ASSESSABLE
        assert score == 0.0
        assert ev.evidence_rationale

    @pytest.mark.parametrize(
        "recon,ec,tier",
        [
            ("full", "concordant", EvidenceTier.HIGH),
            ("full", "unknown", EvidenceTier.HIGH),
            ("full", "discordant", EvidenceTier.MODERATE),
            ("partial", "concordant", EvidenceTier.MODERATE),
            ("partial", "unknown", EvidenceTier.MODERATE),
            ("partial", "discordant", EvidenceTier.LOW),
            ("unverifiable", "concordant", EvidenceTier.MODERATE),
            ("unverifiable", "unknown", EvidenceTier.LOW),
            ("unverifiable", "discordant", EvidenceTier.LOW),
            ("none_contradictory", "concordant", EvidenceTier.LOW),
            ("none_contradictory", "unknown", EvidenceTier.LOW),
            ("none_contradictory", "discordant", EvidenceTier.LOW),
        ],
    )
    def test_decision_table(self, scorer, recon, ec, tier):
        ev = _ev(True, recon, ec)
        scorer.score(ev)
        assert ev.evidence_tier == tier

    def test_contradiction_is_low_even_with_concordant_ec(self, scorer):
        """A shared enzyme class on a disjoint substrate set is coincidental."""
        ev = _ev(True, "none_contradictory", "concordant")
        scorer.score(ev)
        assert ev.evidence_tier == EvidenceTier.LOW

    def test_ec_discordance_never_yields_high(self, scorer):
        ev = _ev(True, "full", "discordant")
        scorer.score(ev)
        assert ev.evidence_tier != EvidenceTier.HIGH

    def test_confidence_score_is_monotone_in_tier(self, scorer):
        assert scorer.score(_ev(True, "full", "concordant")) == 1.0
        assert scorer.score(_ev(True, "partial", "unknown")) == 0.6
        assert scorer.score(_ev(True, "unverifiable", "unknown")) == 0.3
        assert scorer.score(_ev(False, "unverifiable", "unknown")) == 0.0

    def test_bigg_is_not_an_evidence_source(self, scorer):
        ev = _ev(True, "full", "concordant")
        # A BiGG item must not influence the tier or the (zeroed) bigg_score.
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.STRONG,
                description="Found in many BiGG models",
            )
        ]
        scorer.score(ev)
        assert ev.bigg_score == 0.0
        assert ev.evidence_tier == EvidenceTier.HIGH  # from KEGG states only

    def test_kegg_score_reflects_best_kegg_item(self, scorer):
        ev = _ev(True, "full", "concordant")
        ev.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.WEAK,
                description="weak",
            ),
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="strong",
            ),
        ]
        scorer.score(ev)
        assert ev.kegg_score == 1.0

    def test_no_items(self, scorer):
        ev = ReactionEvidence(reaction_id="EMPTY")
        score = scorer.score(ev)
        assert score == 0.0
        assert ev.evidence_tier == EvidenceTier.NOT_ASSESSABLE
        assert ev.kegg_score == 0.0
        assert ev.bigg_score == 0.0

    def test_score_breakdown_still_reports_sources(self, scorer):
        ev = _ev(True, "full", "concordant")
        scorer.score(ev)
        breakdown = scorer.score_breakdown(ev)
        assert set(breakdown) == {"kegg", "bigg"}
