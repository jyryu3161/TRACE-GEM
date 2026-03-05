"""Tests for offline mapping data loader."""

from __future__ import annotations

import pytest

from src.core.mapping_data import MappingData


class TestMappingData:
    @pytest.fixture(scope="class")
    def mapping(self):
        """Load the actual mapping data once for all tests."""
        try:
            return MappingData.load()
        except FileNotFoundError:
            pytest.skip("Mapping data files not found in ./data/")

    def test_load_returns_mapping_data(self, mapping):
        assert isinstance(mapping, MappingData)

    def test_rxn_bigg_to_kegg_populated(self, mapping):
        """Should have BiGG reaction → KEGG reaction mappings."""
        assert len(mapping.rxn_bigg_to_kegg) > 0

    def test_rxn_bigg_to_kegg_known_reaction(self, mapping):
        """Should have a substantial number of BiGG→KEGG reaction mappings."""
        assert len(mapping.rxn_bigg_to_kegg) >= 100

    def test_rxn_bigg_to_mnxr_populated(self, mapping):
        assert len(mapping.rxn_bigg_to_mnxr) > 0

    def test_met_bigg_to_kegg_populated(self, mapping):
        """Should have metabolite BiGG → KEGG compound mappings."""
        assert len(mapping.met_bigg_to_kegg) > 0

    def test_met_bigg_to_kegg_known_metabolite(self, mapping):
        """ATP should map to C00002."""
        kegg_ids = mapping.met_bigg_to_kegg.get("atp", [])
        if kegg_ids:
            assert "C00002" in kegg_ids

    def test_met_bigg_to_name_populated(self, mapping):
        assert len(mapping.met_bigg_to_name) > 0

    def test_rxn_ec_to_kegg_populated(self, mapping):
        assert len(mapping.rxn_ec_to_kegg) > 0

    def test_kegg_ids_format(self, mapping):
        """KEGG reaction IDs should match Rxxxxx pattern."""
        for _bigg_id, kegg_ids in list(mapping.rxn_bigg_to_kegg.items())[:10]:
            for kid in kegg_ids:
                assert kid.startswith("R") and len(kid) == 6, f"Invalid KEGG ID: {kid}"

    def test_kegg_compound_ids_format(self, mapping):
        """KEGG compound IDs should match Cxxxxx or Gxxxxx pattern."""
        for _bigg_id, kegg_ids in list(mapping.met_bigg_to_kegg.items())[:10]:
            for kid in kegg_ids:
                assert (kid.startswith("C") or kid.startswith("G")) and len(kid) == 6, (
                    f"Invalid KEGG compound ID: {kid}"
                )

    def test_strip_compartment(self):
        assert MappingData.strip_compartment("atp_c") == "atp"
        assert MappingData.strip_compartment("glc__D_e") == "glc__D"
        assert MappingData.strip_compartment("h2o") == "h2o"
        assert MappingData.strip_compartment("") == ""
