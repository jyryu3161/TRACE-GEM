"""Offline regression guard for the KEGG-only tier invariants.

Locks the publication-critical property — a deliberately-wrong reaction is never
scored High — into CI without touching the network. The full statistical
validation lives in ``scripts/validate_evidence_tiers.py`` (run against iML1515).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.api.kegg_client import KEGGClient
from src.core.models import EvidenceTier, ReactionEvidence
from src.evidence.scoring import ConfidenceScorer

# KEGG flat-file entries (compounds chosen outside the currency set).
_ENTRIES = {
    "R1": (
        "ENTRY       R1                          Reaction\n"
        "NAME        test reaction one\n"
        "EQUATION    C10001 <=> C10002\n"
        "ENZYME      1.1.1.1\n"
        "///\n"
    ),
    "R2": (
        "ENTRY       R2                          Reaction\n"
        "NAME        test reaction two\n"
        "EQUATION    C10003 <=> C10004\n"
        "ENZYME      2.2.2.2\n"
        "///\n"
    ),
}


def _make_client() -> KEGGClient:
    client = KEGGClient(organism_code="eco", cache_manager=None)

    async def fake_get(path: str, **kwargs):
        if path.startswith("/get/"):
            return _ENTRIES.get(path.split("/get/", 1)[1])
        # No EC→reaction links: decoys cannot be rescued via EC fallback.
        return None

    client.get = AsyncMock(side_effect=fake_get)
    return client


async def _tier(client, scorer, kegg_ids, subs, prods, ec) -> EvidenceTier:
    items = await client.check_evidence(
        None,
        kegg_reaction_ids=kegg_ids,
        ec_numbers=ec,
        model_substrates_kegg=subs,
        model_products_kegg=prods,
    )
    ev = ReactionEvidence(reaction_id="x")
    ev.items = items
    raw = items[0].raw_data if (items and items[0].raw_data) else {}
    ev.kegg_anchored = bool(raw.get("kegg_anchored", False))
    ev.reconciliation_state = raw.get("reconciliation_state", "unverifiable")
    ev.ec_concordance_state = raw.get("ec_concordance_state", "unknown")
    scorer.score(ev)
    return ev.evidence_tier


@pytest.mark.asyncio
async def test_correct_reaction_is_high():
    client, scorer = _make_client(), ConfidenceScorer()
    tier = await _tier(client, scorer, ["R1"], ["C10001"], ["C10002"], ["1.1.1.1"])
    assert tier == EvidenceTier.HIGH


@pytest.mark.asyncio
async def test_wrong_identity_decoy_never_high():
    """Swap KEGG id + EC to another reaction, keep this reaction's metabolites."""
    client, scorer = _make_client(), ConfidenceScorer()
    tier = await _tier(client, scorer, ["R2"], ["C10001"], ["C10002"], ["2.2.2.2"])
    assert tier != EvidenceTier.HIGH
    assert tier == EvidenceTier.LOW  # KEGG entry contradicts the model metabolites


@pytest.mark.asyncio
async def test_metabolite_shuffle_decoy_never_high():
    """Keep the real KEGG id + EC, replace metabolites with another reaction's."""
    client, scorer = _make_client(), ConfidenceScorer()
    tier = await _tier(client, scorer, ["R1"], ["C10003"], ["C10004"], ["1.1.1.1"])
    assert tier != EvidenceTier.HIGH


@pytest.mark.asyncio
async def test_no_kegg_route_is_not_assessable():
    client, scorer = _make_client(), ConfidenceScorer()
    tier = await _tier(client, scorer, [], ["C10001"], ["C10002"], [])
    assert tier == EvidenceTier.NOT_ASSESSABLE


@pytest.mark.asyncio
async def test_ec_discordance_caps_full_at_moderate():
    """A full metabolite match with a discordant EC must not reach High."""
    client, scorer = _make_client(), ConfidenceScorer()
    # R1 metabolites match fully, but the model EC (9.9.9.9) disagrees with R1's.
    tier = await _tier(client, scorer, ["R1"], ["C10001"], ["C10002"], ["9.9.9.9"])
    assert tier == EvidenceTier.MODERATE
