"""Tests for Perplexity API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    )


class TestPerplexityClient:
    @pytest.fixture
    def mock_openai(self):
        """Mock AsyncOpenAI client."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"exists_in_organism": true, "confidence": 0.9, '
            '"evidence_summary": "Well-documented enzyme", "sources": ["KEGG", "BRENDA"]}'
        )
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client.close = AsyncMock()
        return mock_client

    @pytest.fixture
    def client(self, mock_openai):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            from src.api.perplexity_client import PerplexityClient

            c = PerplexityClient.__new__(PerplexityClient)
            c._client = mock_openai
            c._cache = None
            from src.api.rate_limiter import RateLimiter

            c._rate_limiter = RateLimiter(rate=100.0, burst=100)
            return c

    @pytest.mark.asyncio
    async def test_verify_exists(self, client, sample_rxn):
        item = await client.verify_reaction_existence(sample_rxn, "Escherichia coli", ["4.2.1.11"])
        assert item.source == EvidenceSource.PERPLEXITY
        assert item.strength == EvidenceStrength.STRONG
        assert "Found" in item.description
        assert item.raw_data["exists_in_organism"] is True
        assert item.raw_data["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_verify_not_found(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[0].message.content = (
            '{"exists_in_organism": false, "confidence": 0.8, '
            '"evidence_summary": "Not found in this organism", "sources": []}'
        )
        item = await client.verify_reaction_existence(sample_rxn, "Homo sapiens", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.WEAK
        assert "Not found" in item.description

    @pytest.mark.asyncio
    async def test_verify_uncertain(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[0].message.content = (
            '{"exists_in_organism": null, "confidence": 0.3, '
            '"evidence_summary": "Insufficient data", "sources": []}'
        )
        item = await client.verify_reaction_existence(sample_rxn, "Unknown organism", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.WEAK
        assert "Uncertain" in item.description

    @pytest.mark.asyncio
    async def test_verify_moderate_confidence(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[0].message.content = (
            '{"exists_in_organism": true, "confidence": 0.5, '
            '"evidence_summary": "Some evidence", "sources": ["literature"]}'
        )
        item = await client.verify_reaction_existence(sample_rxn, "E. coli", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.MODERATE

    @pytest.mark.asyncio
    async def test_verify_json_in_markdown(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[0].message.content = (
            '```json\n{"exists_in_organism": true, "confidence": 0.85, '
            '"evidence_summary": "Found", "sources": ["KEGG"]}\n```'
        )
        item = await client.verify_reaction_existence(sample_rxn, "E. coli", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.STRONG

    @pytest.mark.asyncio
    async def test_verify_invalid_json_fallback(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[
            0
        ].message.content = "Yes, this enzyme exists in E. coli and is well documented."
        item = await client.verify_reaction_existence(sample_rxn, "E. coli", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.MODERATE
        assert item.raw_data.get("fallback") is True

    @pytest.mark.asyncio
    async def test_verify_no_match_fallback(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.return_value.choices[
            0
        ].message.content = "Cannot determine."
        item = await client.verify_reaction_existence(sample_rxn, "Unknown", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.WEAK

    @pytest.mark.asyncio
    async def test_verify_api_error(self, client, mock_openai, sample_rxn):
        mock_openai.chat.completions.create.side_effect = RuntimeError("API down")
        item = await client.verify_reaction_existence(sample_rxn, "E. coli", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.WEAK
        assert "error" in item.raw_data

    @pytest.mark.asyncio
    async def test_verify_with_cache(self, client, mock_openai, sample_rxn):
        """Cached results should be returned without API call."""
        cache = MagicMock()
        cache.get = AsyncMock(
            return_value={
                "exists_in_organism": True,
                "confidence": 0.95,
                "evidence_summary": "Cached result",
                "sources": ["cache"],
            }
        )
        cache.set = AsyncMock()
        client._cache = cache

        item = await client.verify_reaction_existence(sample_rxn, "E. coli", ["4.2.1.11"])
        assert item.strength == EvidenceStrength.STRONG
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_close(self, client, mock_openai):
        await client.close()
        mock_openai.close.assert_awaited_once()
