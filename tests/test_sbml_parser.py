"""Tests for SBML parser."""

import pytest
from cobra.io.sbml import CobraSBMLError

from src.core.sbml_parser import SBMLParser


class TestSBMLParser:
    @pytest.fixture
    def parser(self):
        return SBMLParser()

    def test_load_mini_model(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        assert model.id == "mini_test_model"
        assert model.reaction_count >= 2  # HEX1, ENO (+ exchange)
        assert model.metabolite_count >= 7
        assert model.gene_count >= 1

    def test_eno_reaction(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        eno = model.get_reaction("ENO")
        if eno is None:
            # COBRApy may prefix with R_
            eno = model.get_reaction("R_ENO")
        assert eno is not None
        assert "enolase" in eno.name.lower()
        assert len(eno.genes) >= 1

    def test_exchange_reaction(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        # Find exchange reactions
        exchanges = [r for r in model.reactions if "EX_" in r.id or "exchange" in r.name.lower()]
        assert len(exchanges) >= 1

    def test_subsystems(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        subs = model.get_subsystems()
        # Should have at least Glycolysis
        assert len(subs) >= 1

    def test_file_not_found(self, parser):
        with pytest.raises(FileNotFoundError):
            parser.load_model("/nonexistent/model.xml")

    def test_organism_detection(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        # mini_test_model won't auto-detect, but shouldn't crash
        assert model.id == "mini_test_model"

    def test_genes_parsed(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        assert model.gene_count >= 1
        gene_ids = [g.id for g in model.genes]
        assert len(gene_ids) >= 1

    def test_metabolites_have_names(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        for met in model.metabolites:
            assert met.name, f"Metabolite {met.id} has no name"

    def test_reactions_have_stoichiometry(self, parser, mini_model_path):
        model = parser.load_model(mini_model_path)
        eno = None
        for r in model.reactions:
            if "ENO" in r.id:
                eno = r
                break
        if eno:
            assert len(eno.reactants) > 0 or len(eno.products) > 0

    def test_invalid_xml_raises(self, parser, tmp_path):
        bad_file = tmp_path / "bad.xml"
        bad_file.write_text("this is not xml")
        with pytest.raises((ValueError, RuntimeError, OSError, CobraSBMLError)):
            parser.load_model(bad_file)

    def test_empty_model_file(self, parser, tmp_path):
        empty_file = tmp_path / "empty.xml"
        empty_file.write_text("")
        with pytest.raises((ValueError, RuntimeError, OSError, CobraSBMLError)):
            parser.load_model(empty_file)
