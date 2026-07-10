"""Tests for OrganismFilter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.base_client import APIUnavailableError
from src.core.models import CandidateReaction, Reaction
from src.gapfill.organism_filter import OrganismFilter


@pytest.fixture
def mock_mapping_data() -> MagicMock:
    mapping = MagicMock()
    mapping.rxn_bigg_to_kegg = {
        "PFK": ["R00756"],
        "GLNS": ["R00253"],
    }
    mapping.rxn_ec_to_kegg = {
        "2.7.1.11": ["R00756"],
        "6.3.1.2": ["R00253"],
    }
    mapping.rxn_bigg_to_mnxr = {}
    return mapping


@pytest.fixture
def sample_candidates() -> list[CandidateReaction]:
    return [
        CandidateReaction(
            reaction=Reaction(
                id="GLNS",
                name="Glutamine synthetase",
                equation="glu + atp + nh4 -> gln + adp + pi",
                annotation={"KEGG Reaction": ["R00253"]},
            ),
        ),
        CandidateReaction(
            reaction=Reaction(
                id="TKT1",
                name="Transketolase",
                equation="r5p + xu5p -> g3p + s7p",
                annotation={"KEGG Reaction": ["R01641"]},
            ),
        ),
        CandidateReaction(
            reaction=Reaction(
                id="UNKNOWN_RXN",
                name="Unknown reaction",
                equation="a -> b",
                annotation={},
            ),
        ),
    ]


MOCK_ORGANISM_KO = "eco:b0485\tko:K01915\neco:b1297\tko:K01915\neco:b2388\tko:K00850\n"

MOCK_ORGANISM_EC = "eco:b1779\tec:1.1.1.1\n"

MOCK_KO_REACTIONS = "ko:K01915\trn:R00253\nko:K00850\trn:R00756\n"

MOCK_EC_REACTIONS = "ec:1.1.1.1\trn:R00200\n"


class TestOrganismFilter:
    @pytest.mark.asyncio
    async def test_load_organism_reactions(self) -> None:
        """KEGG organism reaction set is loaded and parsed correctly."""
        filt = OrganismFilter("eco")

        async def mock_get(path, cache_key=None, cache_ttl=None):
            if path == "/link/ko/eco":
                return MOCK_ORGANISM_KO
            if path == "/link/ec/eco":
                return MOCK_ORGANISM_EC
            if path == "/link/rn/ko":
                return MOCK_KO_REACTIONS
            if path == "/link/rn/ec":
                return MOCK_EC_REACTIONS
            return None

        with patch.object(filt._kegg_client, "get", side_effect=mock_get):
            await filt.initialize()

        assert filt._organism_reactions is not None
        assert "R00253" in filt._organism_reactions
        assert "R00200" in filt._organism_reactions
        assert "R00756" in filt._organism_reactions
        assert len(filt._organism_reactions) == 3

    @pytest.mark.asyncio
    async def test_filter_candidates_sets_organism_exists(
        self,
        sample_candidates: list[CandidateReaction],
    ) -> None:
        """Candidates with matching KEGG IDs get organism_exists=True."""
        filt = OrganismFilter("eco")

        async def mock_get(path, cache_key=None, cache_ttl=None):
            if path == "/link/ko/eco":
                return MOCK_ORGANISM_KO
            if path == "/link/ec/eco":
                return MOCK_ORGANISM_EC
            if path == "/link/rn/ko":
                return MOCK_KO_REACTIONS
            if path == "/link/rn/ec":
                return MOCK_EC_REACTIONS
            return None

        with patch.object(filt._kegg_client, "get", side_effect=mock_get):
            await filt.initialize()
            result = await filt.filter_candidates(sample_candidates)

        # GLNS has R00253 which is in the organism set
        assert result[0].organism_exists is True
        # TKT1 has R01641 which is NOT in the organism set
        assert result[1].organism_exists is False
        # UNKNOWN_RXN has no KEGG annotation
        assert result[2].organism_exists is None

    @pytest.mark.asyncio
    async def test_filter_candidates_gets_genes(
        self,
        sample_candidates: list[CandidateReaction],
    ) -> None:
        """Genes are populated for organism-existing reactions."""
        filt = OrganismFilter("eco")

        async def mock_get(path, cache_key=None, cache_ttl=None):
            if path == "/link/ko/eco":
                return MOCK_ORGANISM_KO
            if path == "/link/ec/eco":
                return MOCK_ORGANISM_EC
            if path == "/link/rn/ko":
                return MOCK_KO_REACTIONS
            if path == "/link/rn/ec":
                return MOCK_EC_REACTIONS
            return None

        with patch.object(filt._kegg_client, "get", side_effect=mock_get):
            await filt.initialize()
            await filt.filter_candidates(sample_candidates)

        assert "b0485" in sample_candidates[0].kegg_organism_genes
        assert "b1297" in sample_candidates[0].kegg_organism_genes

    @pytest.mark.asyncio
    async def test_resolve_kegg_ids_from_annotation(self) -> None:
        """KEGG IDs are resolved directly from annotation."""
        filt = OrganismFilter("eco")
        candidate = CandidateReaction(
            reaction=Reaction(
                id="TEST",
                name="Test",
                equation="a -> b",
                annotation={"KEGG Reaction": ["R12345"]},
            ),
        )
        ids = filt._resolve_kegg_ids(candidate)
        assert ids == ["R12345"]

    @pytest.mark.asyncio
    async def test_resolve_kegg_ids_from_bigg_mapping(self, mock_mapping_data: MagicMock) -> None:
        """KEGG IDs are resolved via BiGG mapping when annotation is empty."""
        filt = OrganismFilter("eco", mapping_data=mock_mapping_data)
        candidate = CandidateReaction(
            reaction=Reaction(
                id="PFK",
                name="Phosphofructokinase",
                equation="atp + f6p -> adp + fdp",
                annotation={},
            ),
        )
        ids = filt._resolve_kegg_ids(candidate)
        assert "R00756" in ids

    @pytest.mark.asyncio
    async def test_resolve_kegg_ids_from_ec_mapping(self, mock_mapping_data: MagicMock) -> None:
        """KEGG IDs are resolved via EC number mapping as fallback."""
        filt = OrganismFilter("eco", mapping_data=mock_mapping_data)
        candidate = CandidateReaction(
            reaction=Reaction(
                id="NOVEL_RXN",
                name="Novel",
                equation="a -> b",
                annotation={"EC Number": ["6.3.1.2"]},
            ),
        )
        ids = filt._resolve_kegg_ids(candidate)
        assert "R00253" in ids

    @pytest.mark.asyncio
    async def test_empty_kegg_response(self) -> None:
        """Empty KEGG response results in empty organism reaction set."""
        filt = OrganismFilter("unknown_org")

        with patch.object(filt._kegg_client, "get", new_callable=AsyncMock, return_value=None):
            await filt.initialize()

        assert filt._organism_reactions == set()
        assert filt._organism_data_complete is False

    @pytest.mark.asyncio
    async def test_unavailable_organism_data_is_unknown_not_absent(
        self, sample_candidates: list[CandidateReaction]
    ) -> None:
        filt = OrganismFilter("eco")
        with patch.object(
            filt._kegg_client,
            "get",
            new_callable=AsyncMock,
            side_effect=APIUnavailableError("offline"),
        ):
            await filt.initialize()
            result = await filt.filter_candidates(sample_candidates)

        assert result[0].organism_exists is None
        assert result[1].organism_exists is None
        assert result[2].organism_exists is None

    @pytest.mark.asyncio
    async def test_progress_callback(self, sample_candidates: list[CandidateReaction]) -> None:
        """Progress callback is invoked for each candidate."""
        filt = OrganismFilter("eco")
        callback = MagicMock()

        async def mock_get(path, cache_key=None, cache_ttl=None):
            if path == "/link/ko/eco":
                return MOCK_ORGANISM_KO
            if path == "/link/ec/eco":
                return MOCK_ORGANISM_EC
            if path == "/link/rn/ko":
                return MOCK_KO_REACTIONS
            if path == "/link/rn/ec":
                return MOCK_EC_REACTIONS
            return None

        with patch.object(filt._kegg_client, "get", side_effect=mock_get):
            await filt.initialize()
            await filt.filter_candidates(sample_candidates, progress_callback=callback)

        assert callback.call_count == len(sample_candidates)

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """close() delegates to kegg client."""
        filt = OrganismFilter("eco")
        with patch.object(filt._kegg_client, "close", new_callable=AsyncMock) as mock_close:
            await filt.close()
        mock_close.assert_called_once()
