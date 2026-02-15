"""Tests for KEGG API client with reaction verification."""

from unittest.mock import AsyncMock

import pytest

from src.api.kegg_client import (
    KEGGClient,
    KEGGReactionData,
    compute_match_ratio,
    parse_kegg_reaction,
)
from src.core.models import EvidenceSource, EvidenceStrength

SAMPLE_KEGG_REACTION = """\
ENTRY       R00658                      Reaction
NAME        2-phospho-D-glycerate hydro-lyase
DEFINITION  2-Phospho-D-glycerate <=> Phosphoenolpyruvate + H2O
EQUATION    C00631 <=> C00074 + C00001
ENZYME      4.2.1.11
PATHWAY     rn00010  Glycolysis / Gluconeogenesis
            rn00680  Methane metabolism
///
"""

IRREVERSIBLE_KEGG_REACTION = """\
ENTRY       R00200                      Reaction
NAME        ATP:D-glucose 6-phosphotransferase
DEFINITION  ATP + D-Glucose => ADP + D-Glucose 6-phosphate
EQUATION    C00002 + C00031 => C00008 + C00092
ENZYME      2.7.1.1  2.7.1.2
PATHWAY     rn00010  Glycolysis / Gluconeogenesis
///
"""


class TestParseKeggReaction:
    def test_parse_basic(self):
        data = parse_kegg_reaction(SAMPLE_KEGG_REACTION)
        assert data is not None
        assert data.entry_id == "R00658"
        assert "hydro-lyase" in data.name
        assert data.is_reversible is True
        assert "C00631" in data.substrates
        assert "C00074" in data.products
        assert "C00001" in data.products
        assert "4.2.1.11" in data.enzyme
        assert "rn00010" in data.pathway_ids
        assert "rn00680" in data.pathway_ids

    def test_parse_irreversible(self):
        data = parse_kegg_reaction(IRREVERSIBLE_KEGG_REACTION)
        assert data is not None
        assert data.entry_id == "R00200"
        assert data.is_reversible is False
        assert "C00002" in data.substrates
        assert "C00031" in data.substrates
        assert "C00008" in data.products
        assert "C00092" in data.products

    def test_parse_none(self):
        assert parse_kegg_reaction(None) is None
        assert parse_kegg_reaction("") is None

    def test_parse_invalid(self):
        assert parse_kegg_reaction("random text without fields") is None

    def test_parse_no_entry(self):
        # Text without ENTRY field
        text = "NAME  test reaction\nEQUATION C00001 = C00002\n///"
        result = parse_kegg_reaction(text)
        assert result is None


class TestComputeMatchRatio:
    def test_perfect_match(self):
        assert compute_match_ratio(["C00631"], ["C00631"]) == 1.0

    def test_no_match(self):
        assert compute_match_ratio(["C00631"], ["C99999"]) == 0.0

    def test_partial_match(self):
        ratio = compute_match_ratio(["C00001", "C00002"], ["C00002", "C00003"])
        # Intersection: {C00002}, Union: {C00001, C00002, C00003}
        assert ratio == pytest.approx(1 / 3)

    def test_both_empty(self):
        assert compute_match_ratio([], []) == 1.0

    def test_one_empty(self):
        assert compute_match_ratio(["C00001"], []) == 0.0
        assert compute_match_ratio([], ["C00001"]) == 0.0

    def test_model_subset(self):
        ratio = compute_match_ratio(["C00001"], ["C00001", "C00002"])
        # Intersection: {C00001}, Union: {C00001, C00002}
        assert ratio == pytest.approx(0.5)


class TestKEGGClient:
    @pytest.fixture
    def client(self):
        return KEGGClient(organism_code="eco", cache_manager=None)

    def test_organism_code(self, client):
        assert client.organism_code == "eco"

    @pytest.mark.asyncio
    async def test_check_evidence_with_reaction_found(self, client):
        """Reaction exists and metabolites match perfectly."""
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)

        items = await client.check_evidence(
            reaction=None,  # Not used directly
            kegg_reaction_ids=["R00658"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074", "C00001"],
        )
        assert len(items) == 1
        assert items[0].source == EvidenceSource.KEGG
        assert items[0].strength == EvidenceStrength.STRONG
        assert items[0].raw_data is not None
        assert items[0].raw_data["substrate_match"] == 1.0
        assert items[0].raw_data["product_match"] == 1.0
        assert items[0].raw_data["model_substrates"] == ["C00631"]
        assert items[0].raw_data["model_products"] == ["C00074", "C00001"]

    @pytest.mark.asyncio
    async def test_check_evidence_absent(self, client):
        """No KEGG reaction found → ABSENT."""
        client.get = AsyncMock(return_value=None)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=[],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074"],
        )
        assert len(items) == 1
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_check_evidence_partial_match(self, client):
        """Partial metabolite match → MODERATE or WEAK."""
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=["R00658"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074"],  # Missing C00001 (h2o)
        )
        assert len(items) == 1
        # avg_match = (1.0 + 0.5) / 2 = 0.75 → MODERATE
        assert items[0].strength in (EvidenceStrength.MODERATE, EvidenceStrength.STRONG)

    @pytest.mark.asyncio
    async def test_check_evidence_ec_fallback(self, client):
        """When no KEGG IDs, falls back to EC number lookup."""
        call_count = 0

        async def mock_get(path, **kwargs):
            nonlocal call_count
            call_count += 1
            if "link/reaction" in path:
                return "ec:4.2.1.11\trn:R00658\n"
            if "R00658" in path:
                return SAMPLE_KEGG_REACTION
            return None

        client.get = AsyncMock(side_effect=mock_get)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=[],
            ec_numbers=["4.2.1.11"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074", "C00001"],
        )
        assert len(items) == 1
        assert items[0].source == EvidenceSource.KEGG
        assert items[0].strength == EvidenceStrength.STRONG

    @pytest.mark.asyncio
    async def test_check_evidence_best_match_wins(self, client):
        """When multiple KEGG IDs, the best match should be used."""

        async def mock_get(path, **kwargs):
            if "R00658" in path:
                return SAMPLE_KEGG_REACTION  # Good match
            if "R99999" in path:
                return None  # Not found
            return None

        client.get = AsyncMock(side_effect=mock_get)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=["R99999", "R00658"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074", "C00001"],
        )
        assert len(items) == 1
        assert items[0].strength == EvidenceStrength.STRONG

    @pytest.mark.asyncio
    async def test_check_evidence_raw_data_has_kegg_parsed(self, client):
        """Raw data should contain kegg_parsed for downstream LLM verification."""
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=["R00658"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074", "C00001"],
        )
        assert items[0].raw_data is not None
        kegg_parsed = items[0].raw_data.get("kegg_parsed")
        assert kegg_parsed is not None
        assert isinstance(kegg_parsed, KEGGReactionData)
        assert kegg_parsed.entry_id == "R00658"

    @pytest.mark.asyncio
    async def test_zero_match_returns_absent(self, client):
        """When metabolites don't overlap at all, should return ABSENT — not WEAK."""
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)

        # SAMPLE_KEGG_REACTION has substrates=[C00631], products=[C00074, C00001]
        # Provide completely unrelated metabolites
        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=["R00658"],
            model_substrates_kegg=["C99999"],
            model_products_kegg=["C88888"],
        )
        assert len(items) == 1
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_description_has_overlap_counts(self, client):
        """Description should show overlap counts like 'substrates: 1/1 matched'."""
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)

        items = await client.check_evidence(
            reaction=None,
            kegg_reaction_ids=["R00658"],
            model_substrates_kegg=["C00631"],
            model_products_kegg=["C00074", "C00001"],
        )
        desc = items[0].description
        assert "substrates:" in desc
        assert "products:" in desc
        assert "matched" in desc
        # Should have fraction like "1/1"
        assert "1/1" in desc

    @pytest.mark.asyncio
    async def test_get_reaction_parsed(self, client):
        client.get = AsyncMock(return_value=SAMPLE_KEGG_REACTION)
        parsed = await client.get_reaction_parsed("R00658")
        assert parsed is not None
        assert isinstance(parsed, KEGGReactionData)
        assert parsed.entry_id == "R00658"
