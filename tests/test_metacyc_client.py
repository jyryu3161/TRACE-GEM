"""Tests for MetaCyc API client."""

from unittest.mock import AsyncMock

import pytest

from src.api.metacyc_client import MetaCycClient
from src.core.models import EvidenceStrength, Reaction


class TestMetaCycClient:
    @pytest.fixture
    def client(self):
        return MetaCycClient(cache_manager=None)

    @pytest.fixture
    def sample_rxn(self):
        return Reaction(id="ENO", name="enolase", equation="2pg <=> pep + h2o")

    @pytest.mark.asyncio
    async def test_check_evidence_with_experimental(self, client, sample_rxn):
        client.get = AsyncMock(return_value="<reaction>EV-EXP evidence</reaction>")
        items = await client.check_evidence(sample_rxn, metacyc_ids=["ENOLASE-RXN"])
        assert items[0].strength == EvidenceStrength.STRONG

    @pytest.mark.asyncio
    async def test_check_evidence_documented(self, client, sample_rxn):
        client.get = AsyncMock(return_value="<reaction>some data</reaction>")
        items = await client.check_evidence(sample_rxn, metacyc_ids=["ENOLASE-RXN"])
        assert items[0].strength == EvidenceStrength.MODERATE

    @pytest.mark.asyncio
    async def test_check_evidence_absent(self, client, sample_rxn):
        items = await client.check_evidence(sample_rxn, metacyc_ids=[])
        assert items[0].strength == EvidenceStrength.ABSENT

    @pytest.mark.asyncio
    async def test_check_evidence_not_found(self, client, sample_rxn):
        client.get = AsyncMock(return_value=None)
        items = await client.check_evidence(sample_rxn, metacyc_ids=["NONEXISTENT"])
        assert items[0].strength == EvidenceStrength.ABSENT
