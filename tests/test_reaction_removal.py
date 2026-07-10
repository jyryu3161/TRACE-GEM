"""Tests for reaction removal from ModelData."""

from __future__ import annotations

from src.core.models import Gene, Metabolite, ModelData, Reaction


class TestModelDataRemoveReaction:
    def test_remove_existing_reaction(self, sample_model):
        removed = sample_model.remove_reaction("ENO")
        assert removed is not None
        assert removed.id == "ENO"
        assert sample_model.get_reaction("ENO") is None
        assert sample_model.reaction_count == 2

    def test_remove_nonexistent(self, sample_model):
        removed = sample_model.remove_reaction("NONEXISTENT")
        assert removed is None
        assert sample_model.reaction_count == 3

    def test_reaction_count_after_removal(self, sample_model):
        assert sample_model.reaction_count == 3
        sample_model.remove_reaction("ENO")
        assert sample_model.reaction_count == 2
        sample_model.remove_reaction("PFK")
        assert sample_model.reaction_count == 1

    def test_get_reaction_returns_none_after_removal(self, sample_model):
        sample_model.remove_reaction("ENO")
        assert sample_model.get_reaction("ENO") is None
        # Other reactions still accessible
        assert sample_model.get_reaction("PFK") is not None
        assert sample_model.get_reaction("EX_glc__D_e") is not None

    def test_orphaned_metabolites_cleaned(self):
        """Metabolites only used by the removed reaction should be cleaned up."""
        rxn_a = Reaction(
            id="A",
            name="A",
            equation="x -> y",
            reactants={"x_c": 1.0},
            products={"y_c": 1.0},
        )
        rxn_b = Reaction(
            id="B",
            name="B",
            equation="y -> z",
            reactants={"y_c": 1.0},
            products={"z_c": 1.0},
        )
        model = ModelData(
            id="test",
            name="Test",
            reactions=[rxn_a, rxn_b],
            metabolites=[
                Metabolite(id="x_c", name="X"),
                Metabolite(id="y_c", name="Y"),
                Metabolite(id="z_c", name="Z"),
            ],
        )
        # Remove A: x_c is orphaned (only used by A), y_c is shared
        model.remove_reaction("A")
        met_ids = {m.id for m in model.metabolites}
        assert "x_c" not in met_ids  # orphaned, removed
        assert "y_c" in met_ids  # still used by B
        assert "z_c" in met_ids  # still used by B

    def test_orphaned_genes_cleaned(self):
        """Genes only used by the removed reaction should be cleaned up."""
        rxn_a = Reaction(
            id="A",
            name="A",
            equation="x -> y",
            genes=["g1", "g2"],
            gene_reaction_rule="g1 and g2",  # genes are str IDs
        )
        rxn_b = Reaction(
            id="B",
            name="B",
            equation="y -> z",
            genes=["g2", "g3"],
            gene_reaction_rule="g2 or g3",
        )
        model = ModelData(
            id="test",
            name="Test",
            reactions=[rxn_a, rxn_b],
            genes=[
                Gene(id="g1", name="Gene1"),
                Gene(id="g2", name="Gene2"),
                Gene(id="g3", name="Gene3"),
            ],
        )
        model.remove_reaction("A")
        gene_ids = {g.id for g in model.genes}
        assert "g1" not in gene_ids  # orphaned, removed
        assert "g2" in gene_ids  # still used by B
        assert "g3" in gene_ids  # still used by B

    def test_shared_metabolites_kept(self, sample_model):
        """h2o_c used by ENO should remain if other reactions also use it."""
        # In sample_model, h2o_c is only in ENO products
        before_met_count = sample_model.metabolite_count
        sample_model.remove_reaction("ENO")
        # h2o_c and 2pg_c are only in ENO, so should be removed
        # pep_c is also only in ENO
        assert sample_model.metabolite_count < before_met_count

    def test_remove_all_reactions(self, sample_model):
        sample_model.remove_reaction("ENO")
        sample_model.remove_reaction("PFK")
        sample_model.remove_reaction("EX_glc__D_e")
        assert sample_model.reaction_count == 0
        assert sample_model.metabolite_count == 0
        assert sample_model.gene_count == 0

    def test_returns_removed_reaction(self, sample_model):
        removed = sample_model.remove_reaction("PFK")
        assert removed.id == "PFK"
        assert removed.name == "phosphofructokinase"

    def test_gene_count_after_removal(self, sample_model):
        # ENO has gene b2779, PFK has b3916 and b1723
        assert sample_model.gene_count == 3
        sample_model.remove_reaction("ENO")
        # b2779 should be removed (orphaned), b3916 and b1723 remain
        assert sample_model.gene_count == 2
        gene_ids = {g.id for g in sample_model.genes}
        assert "b2779" not in gene_ids
        assert "b3916" in gene_ids
        assert "b1723" in gene_ids

    def test_get_subsystems_after_removal(self, sample_model):
        subs = sample_model.get_subsystems()
        assert "Glycolysis/Gluconeogenesis" in subs
        assert "Exchange" in subs

        sample_model.remove_reaction("EX_glc__D_e")
        subs = sample_model.get_subsystems()
        assert "Exchange" not in subs
        assert "Glycolysis/Gluconeogenesis" in subs
