"""Tests for PenaltyCalculator."""

from __future__ import annotations

import pytest

from src.core.models import CandidateReaction, Reaction, ReactionEvidence
from src.gapfill.penalty_calculator import PenaltyCalculator
from src.utils.config import Config


def _make_candidate(organism_exists: bool | None = True) -> CandidateReaction:
    rxn = Reaction(id="TEST_RXN", name="Test", equation="A -> B")
    return CandidateReaction(reaction=rxn, organism_exists=organism_exists)


def _make_evidence(
    score: float, kegg_ids: list[str] | None = None
) -> ReactionEvidence:
    ev = ReactionEvidence(reaction_id="TEST_RXN")
    ev.confidence_score = score
    ev.kegg_reaction_ids = kegg_ids or []
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
        # 1.0 / (0.90 + 0.01) = ~1.099
        assert penalty == pytest.approx(1.0 / 0.91, rel=1e-3)
        assert penalty < 2.0

    def test_low_score_high_penalty(self, calc: PenaltyCalculator) -> None:
        """Low evidence score -> high penalty."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(0.05, kegg_ids=["R00001"])
        penalty = calc.calculate(candidate, evidence)
        # 1.0 / (0.05 + 0.01) = ~16.67
        assert penalty == pytest.approx(1.0 / 0.06, rel=1e-3)
        assert penalty > 10.0

    def test_organism_not_exists_multiplier(self, calc: PenaltyCalculator) -> None:
        """organism_exists=False applies org_mult (10x)."""
        candidate = _make_candidate(organism_exists=False)
        evidence = _make_evidence(0.50, kegg_ids=["R00001"])
        penalty = calc.calculate(candidate, evidence)
        # 1.0 / (0.50 + 0.01) * 10.0 = ~19.6
        expected = (1.0 / 0.51) * 10.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_organism_none_multiplier(self, calc: PenaltyCalculator) -> None:
        """organism_exists=None applies 3x multiplier."""
        candidate = _make_candidate(organism_exists=None)
        evidence = _make_evidence(0.50, kegg_ids=["R00001"])
        penalty = calc.calculate(candidate, evidence)
        expected = (1.0 / 0.51) * 3.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_no_kegg_multiplier(self, calc: PenaltyCalculator) -> None:
        """No KEGG reaction IDs applies no_kegg_mult (2x)."""
        candidate = _make_candidate(organism_exists=True)
        evidence = _make_evidence(0.50, kegg_ids=[])
        penalty = calc.calculate(candidate, evidence)
        expected = (1.0 / 0.51) * 2.0
        assert penalty == pytest.approx(expected, rel=1e-3)

    def test_no_evidence_applies_kegg_multiplier(self, calc: PenaltyCalculator) -> None:
        """None evidence applies no_kegg_mult."""
        candidate = _make_candidate(organism_exists=True)
        penalty = calc.calculate(candidate, None)
        # 1.0 / (0.0 + 0.01) * 2.0 = 200.0
        assert penalty == pytest.approx(200.0, rel=1e-3)

    def test_penalty_capped_at_max(self, calc: PenaltyCalculator) -> None:
        """Penalty is capped at max_penalty (1000.0)."""
        candidate = _make_candidate(organism_exists=False)
        evidence = _make_evidence(0.0, kegg_ids=[])
        penalty = calc.calculate(candidate, evidence)
        # 1.0 / (0.0 + 0.01) * 10.0 * 2.0 = 2000.0 -> capped at 1000.0
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
        # RXN_B: no evidence + organism_exists=False -> capped at 1000
        assert penalties["RXN_B"] == 1000.0
