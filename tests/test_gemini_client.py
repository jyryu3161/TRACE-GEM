"""Tests for Gemini API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.kegg_client import KEGGReactionData
from src.core.models import (
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)


@pytest.fixture
def sample_rxn():
    return Reaction(
        id="ENO",
        name="enolase",
        equation="2pg <=> pep + h2o",
        subsystem="Glycolysis",
        genes=["b2779"],
        reactants={"2pg_c": 1.0},
        products={"pep_c": 1.0, "h2o_c": 1.0},
    )


@pytest.fixture
def kegg_data():
    return KEGGReactionData(
        entry_id="R00658",
        name="2-phospho-D-glycerate hydro-lyase",
        definition="2-Phospho-D-glycerate <=> Phosphoenolpyruvate + H2O",
        equation="C00631 <=> C00074 + C00001",
        enzyme=["4.2.1.11"],
        substrates=["C00631"],
        products=["C00074", "C00001"],
    )


class TestGeminiClient:
    @pytest.fixture
    def mock_genai(self):
        """Mock google.genai module."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"is_correct_match": true, "confidence": 0.9, "reasoning": "Same reaction"}'
        )
        mock_client.models.generate_content.return_value = mock_response
        return mock_client

    @pytest.fixture
    def client(self, mock_genai):
        with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": MagicMock()}):
            from src.api.gemini_client import GeminiClient

            c = GeminiClient.__new__(GeminiClient)
            c._client = mock_genai
            c._cache = None
            from src.api.rate_limiter import RateLimiter

            c._rate_limiter = RateLimiter(rate=100.0, burst=100)
            return c

    @pytest.mark.asyncio
    async def test_verify_match_correct(self, client, sample_rxn, kegg_data):
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 1.0, 1.0, "Escherichia coli"
        )
        assert item.source == EvidenceSource.GEMINI
        assert item.strength == EvidenceStrength.STRONG
        assert "Match" in item.description
        assert item.raw_data["is_correct_match"] is True
        assert item.raw_data["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_verify_match_incorrect(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.return_value.text = (
            '{"is_correct_match": false, "confidence": 0.8, "reasoning": "Different reaction"}'
        )
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 0.3, 0.2, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.WEAK
        assert "Mismatch" in item.description

    @pytest.mark.asyncio
    async def test_verify_moderate_confidence(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.return_value.text = (
            '{"is_correct_match": true, "confidence": 0.5, "reasoning": "Probably same"}'
        )
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 0.7, 0.6, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.MODERATE

    @pytest.mark.asyncio
    async def test_verify_json_in_markdown(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.return_value.text = (
            '```json\n{"is_correct_match": true, "confidence": 0.85, '
            '"reasoning": "Match confirmed"}\n```'
        )
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 1.0, 1.0, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.STRONG

    @pytest.mark.asyncio
    async def test_verify_invalid_json_fallback(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.return_value.text = "Yes, this is true, they match."
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 1.0, 1.0, "Escherichia coli"
        )
        # Fallback parse should find "true"
        assert item.strength == EvidenceStrength.MODERATE
        assert item.raw_data.get("fallback") is True

    @pytest.mark.asyncio
    async def test_verify_no_match_fallback(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.return_value.text = "Cannot determine."
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 0.3, 0.2, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.WEAK

    @pytest.mark.asyncio
    async def test_verify_api_error(self, client, mock_genai, sample_rxn, kegg_data):
        mock_genai.models.generate_content.side_effect = RuntimeError("API down")
        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 1.0, 1.0, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.WEAK
        assert "error" in item.raw_data

    @pytest.mark.asyncio
    async def test_verify_non_kegg_data(self, client, sample_rxn):
        """Non-KEGGReactionData input should return skip item."""
        item = await client.verify_reaction_match(
            sample_rxn, {"not": "kegg_data"}, 1.0, 1.0, "E. coli"
        )
        assert item.strength == EvidenceStrength.WEAK
        assert "skipped" in item.description.lower()

    @pytest.mark.asyncio
    async def test_verify_with_cache(self, client, mock_genai, sample_rxn, kegg_data):
        """Cached results should be returned without API call."""
        cache = MagicMock()
        cache.get = AsyncMock(
            return_value={
                "is_correct_match": True,
                "confidence": 0.95,
                "reasoning": "Cached match",
            }
        )
        cache.set = AsyncMock()
        client._cache = cache

        item = await client.verify_reaction_match(
            sample_rxn, kegg_data, 1.0, 1.0, "Escherichia coli"
        )
        assert item.strength == EvidenceStrength.STRONG
        # API should not have been called
        mock_genai.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_close(self, client):
        await client.close()  # Should not raise
