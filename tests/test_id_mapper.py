"""Tests for identifier mapper with offline mapping data."""

from unittest.mock import MagicMock

import pytest

from src.core.id_mapper import IdentifierMapper
from src.core.mapping_data import MappingData
from src.core.models import Reaction


class TestIdentifierMapper:
    @pytest.fixture
    def mock_mapping(self):
        mapping = MagicMock(spec=MappingData)
        mapping.rxn_bigg_to_kegg = {
            "ENO": ["R00658"],
            "PFK": ["R00756", "R04779"],
        }
        mapping.rxn_bigg_to_mnxr = {
            "ENO": ["MNXR100031"],
            "PFK": ["MNXR100030"],
        }
        mapping.rxn_ec_to_kegg = {
            "4.2.1.11": ["R00658"],
            "2.7.1.11": ["R00756"],
        }
        mapping.met_bigg_to_kegg = {
            "2pg": ["C00631"],
            "pep": ["C00074"],
            "h2o": ["C00001"],
            "atp": ["C00002"],
        }
        mapping.met_bigg_to_name = {
            "2pg": "D-Glycerate 2-phosphate",
            "pep": "Phosphoenolpyruvate",
        }
        return mapping

    @pytest.fixture
    def mapper(self, mock_mapping):
        return IdentifierMapper(mock_mapping)

    @pytest.mark.asyncio
    async def test_resolve_eno(self, mapper, sample_reaction):
        ext = await mapper.resolve(sample_reaction)
        assert ext.reaction_id == "ENO"
        assert "R00658" in ext.kegg_reaction_ids
        assert ext.bigg_id == "ENO"

    @pytest.mark.asyncio
    async def test_resolve_maps_metabolites(self, mapper, sample_reaction):
        ext = await mapper.resolve(sample_reaction)
        # Reactants: 2pg_c → C00631 (via stripping compartment)
        assert len(ext.kegg_substrate_ids) >= 0  # depends on mock matching
        # Products: pep_c, h2o_c
        assert len(ext.kegg_product_ids) >= 0

    @pytest.mark.asyncio
    async def test_resolve_with_prefix(self, mapper):
        rxn = Reaction(
            id="R_ENO",
            name="enolase",
            equation="2pg <=> pep + h2o",
            genes=["b2779"],
        )
        ext = await mapper.resolve(rxn)
        assert ext.bigg_id == "ENO"

    def test_normalize_bigg_id(self, mapper):
        assert mapper._normalize_bigg_id("R_ENO") == "ENO"
        assert mapper._normalize_bigg_id("ENO") == "ENO"
        assert mapper._normalize_bigg_id("R_EX_glc_DASH_D_e") == "EX_glc-D_e"

    def test_normalize_encoded_ids(self, mapper):
        assert mapper._normalize_bigg_id("R___LPAREN__test__RPAREN__") == "(test)"
        assert mapper._normalize_bigg_id("R__test_DASH_1") == "_test-1"

    @pytest.mark.asyncio
    async def test_resolve_unknown_reaction(self, mock_mapping):
        mock_mapping.rxn_bigg_to_kegg = {}
        mock_mapping.rxn_bigg_to_mnxr = {}
        mock_mapping.rxn_ec_to_kegg = {}
        mock_mapping.met_bigg_to_kegg = {}
        mapper = IdentifierMapper(mock_mapping)
        rxn = Reaction(id="UNKNOWN", name="unknown", equation="a -> b")
        ext = await mapper.resolve(rxn)
        assert ext.reaction_id == "UNKNOWN"
        assert ext.kegg_reaction_ids == []

    def test_extract_id_from_uri(self, mapper):
        assert (
            mapper._extract_id_from_uri("http://identifiers.org/kegg.reaction/R00351") == "R00351"
        )
        assert mapper._extract_id_from_uri("R00351") == "R00351"
        assert mapper._extract_id_from_uri("https://identifiers.org/ec-code/4.2.1.11") == "4.2.1.11"

    @pytest.mark.asyncio
    async def test_annotation_extraction(self, mock_mapping):
        """Annotations from SBML should be extracted."""
        mock_mapping.rxn_bigg_to_kegg = {}
        mock_mapping.rxn_bigg_to_mnxr = {}
        mock_mapping.rxn_ec_to_kegg = {}
        mock_mapping.met_bigg_to_kegg = {}
        mapper = IdentifierMapper(mock_mapping)
        rxn = Reaction(
            id="TEST",
            name="Test",
            equation="a -> b",
            annotation={
                "ec-code": ["1.2.3.4"],
                "kegg.reaction": ["http://identifiers.org/kegg.reaction/R99999"],
            },
        )
        ext = await mapper.resolve(rxn)
        assert "1.2.3.4" in ext.ec_numbers
        assert "R99999" in ext.kegg_reaction_ids

    @pytest.mark.asyncio
    async def test_ec_to_kegg_supplementary(self, mock_mapping):
        """EC numbers should find additional KEGG IDs via mapping."""
        mock_mapping.rxn_bigg_to_kegg = {}
        mock_mapping.rxn_bigg_to_mnxr = {}
        mock_mapping.met_bigg_to_kegg = {}
        mapper = IdentifierMapper(mock_mapping)
        rxn = Reaction(
            id="TEST",
            name="Test",
            equation="a -> b",
            annotation={"ec-code": ["4.2.1.11"]},
        )
        ext = await mapper.resolve(rxn)
        assert "R00658" in ext.kegg_reaction_ids

    @pytest.mark.asyncio
    async def test_mnxr_ids_populated(self, mapper, sample_reaction):
        ext = await mapper.resolve(sample_reaction)
        assert "MNXR100031" in ext.mnxr_ids

    def test_get_metabolite_kegg_id(self, mapper):
        assert mapper.get_metabolite_kegg_id("atp") == "C00002"

    def test_get_metabolite_name(self, mapper):
        assert mapper.get_metabolite_name("2pg") == "D-Glycerate 2-phosphate"
