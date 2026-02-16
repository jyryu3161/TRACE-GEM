"""Tests for BiGG API client."""

from unittest.mock import AsyncMock

import pytest

from src.api.bigg_client import BiGGClient
from src.core.models import EvidenceSource, EvidenceStrength, Reaction


class TestBiGGClient:
    @pytest.fixture
    def client(self):
        return BiGGClient(cache_manager=None)

    @pytest.fixture
    def sample_rxn(self):
        return Reaction(id="ENO", name="enolase", equation="2pg <=> pep + h2o")

    @pytest.mark.asyncio
    async def test_check_evidence_strong(self, client, sample_rxn, mock_bigg_response):
        client.get = AsyncMock(return_value=mock_bigg_response)
        items = await client.check_evidence(sample_rxn, bigg_id="ENO")
        assert len(items) == 1
        assert items[0].source == EvidenceSource.BIGG
        assert items[0].strength == EvidenceStrength.STRONG
        assert "8" in items[0].description

    @pytest.mark.asyncio
    async def test_check_evidence_not_found(self, client, sample_rxn):
        client.get = AsyncMock(return_value=None)
        items = await client.check_evidence(sample_rxn, bigg_id="NONEXISTENT")
        assert len(items) == 1
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_check_evidence_few_models(self, client, sample_rxn):
        data = {
            "models_containing_reaction": [
                {"bigg_id": "iJO1366"},
                {"bigg_id": "iML1515"},
            ],
            "database_links": {},
        }
        client.get = AsyncMock(return_value=data)
        items = await client.check_evidence(sample_rxn, bigg_id="ENO")
        assert items[0].strength == EvidenceStrength.MODERATE

    @pytest.mark.asyncio
    async def test_close(self, client):
        await client.close()  # Should not raise
