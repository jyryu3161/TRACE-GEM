"""Tests for PenaltyCalculator."""

from __future__ import annotations

import pytest

from src.core.models import CandidateReaction, EvidenceTier, Reaction, ReactionEvidence
from src.gapfill.penalty_calculator import PenaltyCalculator
from src.utils.config import Config


def _make_candidate(organism_exists: bool | None = True) -> CandidateReaction:
    rxn = Reaction(id="TEST_RXN", name="Test", equation="A -> B")
    return CandidateReaction(reaction=rxn, organism_exists=organism_exists)


def _make_evidence(
    score: float,
    kegg_ids: list[str] | None = None,
    tier: EvidenceTier = EvidenceTier.HIGH,
    verified: bool = True,
) -> ReactionEvidence:
    ev = ReactionEvidence(reaction_id="TEST_RXN")
    ev.confidence_score = score
    ev.evidence_tier = tier
    ev.kegg_reaction_ids = kegg_ids or []
    # The no-KEGG penalty keys on *verified* KEGG IDs; annotated-only IDs that
    # KEGG verification rejected do not count.
    ev.verified_kegg_reaction_ids = list(kegg_ids or []) if verified else []
    return ev


class TestPenaltyCalculator:
    @pytest.fixture
    def calc(self) -> PenaltyCalculator:
        return PenaltyCalculator(Config())

    def test_high_score_low_penalty(self, calc: PenaltyCalculator) -> None:
        """High evidence score -> low penalty."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(0.90, kegg_ids=["R00001"])
        penalty = calc.calculate(candidate, evidence)
        assert penalty == pytest.approx(1.0, rel=1e-3)
        assert penalty < 2.0

    def test_low_tier_high_penalty(self, calc: PenaltyCalculator) -> None:
        """Low evidence tier -> high penalty."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(0.05, kegg_ids=["R00001"], tier=EvidenceTier.LOW)
        penalty = calc.calculate(candidate, evidence)
        assert penalty == pytest.approx(25.0, rel=1e-3)
        assert penalty > 10.0

    def test_organism_not_exists_multiplier(self, calc: PenaltyCalculator) -> None:
        """organism_exists=False applies org_mult (10x)."""
        candidate = _make_candidate(organism_exists=False)
        evidence = _make_evidence(0.50, kegg_ids=["R00001"], tier=EvidenceTier.MODERATE)
        penalty = calc.calculate(candidate, evidence)
        expected = 5.0 * 10.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_organism_none_multiplier(self, calc: PenaltyCalculator) -> None:
        """organism_exists=None applies 3x multiplier."""
        candidate = _make_candidate(organism_exists=None)
        evidence = _make_evidence(0.50, kegg_ids=["R00001"], tier=EvidenceTier.MODERATE)
        penalty = calc.calculate(candidate, evidence)
        expected = 5.0 * 3.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_no_kegg_multiplier(self, calc: PenaltyCalculator) -> None:
        """No KEGG reaction IDs applies no_kegg_mult (2x)."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(0.50, kegg_ids=[], tier=EvidenceTier.MODERATE)
        penalty = calc.calculate(candidate, evidence)
        expected = 5.0 * 2.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_unverified_kegg_id_still_gets_no_kegg_multiplier(
        self, calc: PenaltyCalculator
    ) -> None:
        """An annotated KEGG ID that was NOT verified must not dodge the no-KEGG
        multiplier (no laundering of rejected/unverified IDs)."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(
            0.50, kegg_ids=["R00001"], tier=EvidenceTier.MODERATE, verified=False
        )
        penalty = calc.calculate(candidate, evidence)
        assert penalty == pytest.approx(5.0 * 2.0, rel=1e-3)

    def test_not_assessable_tier_penalty(self, calc: PenaltyCalculator) -> None:
        """Not-assessable candidates are penalized like Low (plus no-KEGG)."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(
            0.0, kegg_ids=[], tier=EvidenceTier.NOT_ASSESSABLE, verified=False
        )
        penalty = calc.calculate(candidate, evidence)
        assert penalty == pytest.approx(25.0 * 2.0, rel=1e-3)

    def test_no_evidence_applies_kegg_multiplier(self, calc: PenaltyCalculator) -> None:
        """None evidence applies no_kegg_mult."""
        candidate = _make_candidate(organism_exists=True)
        penalty = calc.calculate(candidate, None)
        assert penalty == pytest.approx(50.0, rel=1e-3)

    def test_penalty_capped_at_max(self, calc: PenaltyCalculator) -> None:
        """Penalty is capped at max_penalty (1000.0)."""
        config = Config(gapfill_organism_penalty_multiplier=100.0)
        calc = PenaltyCalculator(config)
        candidate = _make_candidate(organism_exists=False)
        evidence = _make_evidence(0.0, kegg_ids=[], tier=EvidenceTier.LOW)
        penalty = calc.calculate(candidate, evidence)
        assert penalty == 1000.0

    def test_calculate_batch(self, calc: PenaltyCalculator) -> None:
        """calculate_batch returns penalties for all candidates."""
        rxn_a = Reaction(id="RXN_A", name="A", equation="A -> B")
        rxn_b = Reaction(id="RXN_B", name="B", equation="C -> D")
        candidates = [
            CandidateReaction(reaction=rxn_a, organism_exists=True),
            CandidateReaction(reaction=rxn_b, organism_exists=False),
        ]
        evidence_results = {
            "RXN_A": _make_evidence(0.80, kegg_ids=["R00001"]),
            # RXN_B has no evidence
        }
        penalties = calc.calculate_batch(candidates, evidence_results)

        assert "RXN_A" in penalties
        assert "RXN_B" in penalties
        # RXN_A has good evidence, should be low penalty
        assert penalties["RXN_A"] < penalties["RXN_B"]
        # RXN_B: no evidence + organism_exists=False is heavily discouraged.
        assert penalties["RXN_B"] == 500.0
