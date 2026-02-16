"""Tests for UniProt API client."""

from unittest.mock import AsyncMock

import pytest

from src.api.uniprot_client import UniProtClient
from src.core.models import EvidenceSource, EvidenceStrength, Reaction


class TestUniProtClient:
    @pytest.fixture
    def client(self):
        return UniProtClient(taxonomy_id="83333", cache_manager=None)

    @pytest.fixture
    def sample_rxn(self):
        return Reaction(
            id="ENO",
            name="enolase",
            equation="2pg <=> pep + h2o",
            genes=["b2779"],
        )

    @pytest.mark.asyncio
    async def test_check_evidence_strong(self, client, sample_rxn, mock_uniprot_response):
        client.search_by_gene = AsyncMock(return_value=mock_uniprot_response)
        items = await client.check_evidence(sample_rxn, ec_numbers=["4.2.1.11"])
        assert len(items) >= 1
        assert items[0].source == EvidenceSource.UNIPROT
        assert items[0].strength == EvidenceStrength.STRONG
        assert "P0A6P9" in items[0].description

    @pytest.mark.asyncio
    async def test_check_evidence_absent(self, client):
        rxn = Reaction(id="FAKE", name="fake", equation="a -> b", genes=[])
        client.search_by_gene = AsyncMock(return_value={"results": []})
        client.search_by_ec = AsyncMock(return_value={"results": []})
        items = await client.check_evidence(rxn)
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_check_evidence_no_genes_with_ec(self, client):
        rxn = Reaction(id="TEST", name="test", equation="a -> b", genes=[])
        ec_response = {
            "results": [
                {
                    "entryType": "UniProtKB reviewed (Swiss-Prot)",
                    "primaryAccession": "Q12345",
                    "proteinDescription": {
                        "recommendedName": {"fullName": {"value": "Test"}, "ecNumbers": []}
                    },
                }
            ]
        }
        client.search_by_ec = AsyncMock(return_value=ec_response)
        items = await client.check_evidence(rxn, ec_numbers=["1.2.3.4"])
        assert items[0].strength == EvidenceStrength.MODERATE

    def test_extract_ec_numbers(self, client, mock_uniprot_response):
        entry = mock_uniprot_response["results"][0]
        ecs = client._extract_ec_numbers(entry)
        assert "4.2.1.11" in ecs
