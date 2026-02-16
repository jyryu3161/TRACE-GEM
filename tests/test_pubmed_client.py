"""Tests for PubMed API client."""

from unittest.mock import AsyncMock

import pytest

from src.api.pubmed_client import PubMedClient
from src.core.models import EvidenceSource, EvidenceStrength, Reaction


class TestPubMedClient:
    @pytest.fixture
    def client(self):
        return PubMedClient(email="test@example.com", cache_manager=None)

    @pytest.fixture
    def sample_rxn(self):
        return Reaction(id="ENO", name="enolase", equation="2pg <=> pep + h2o")

    @pytest.mark.asyncio
    async def test_check_evidence_strong(self, client, sample_rxn, mock_pubmed_response):
        client.search = AsyncMock(return_value=mock_pubmed_response)
        items = await client.check_evidence(
            sample_rxn,
            ec_numbers=["4.2.1.11"],
            organism_name="Escherichia coli",
        )
        assert len(items) == 1
        assert items[0].source == EvidenceSource.PUBMED
        assert items[0].strength == EvidenceStrength.STRONG
        assert "15" in items[0].description

    @pytest.mark.asyncio
    async def test_check_evidence_absent(self, client, sample_rxn):
        client.search = AsyncMock(return_value={"esearchresult": {"count": "0", "idlist": []}})
        items = await client.check_evidence(sample_rxn)
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_check_evidence_moderate(self, client, sample_rxn):
        client.search = AsyncMock(
            return_value={"esearchresult": {"count": "5", "idlist": ["1", "2", "3", "4", "5"]}}
        )
        items = await client.check_evidence(sample_rxn, ec_numbers=["4.2.1.11"])
        assert items[0].strength == EvidenceStrength.MODERATE

    def test_build_queries(self, client, sample_rxn):
        queries = client._build_queries(sample_rxn, ["4.2.1.11"], "Escherichia coli")
        assert len(queries) >= 1
        assert any("enolase" in q.lower() for q in queries)
