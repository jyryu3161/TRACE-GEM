"""Tests for core data models."""

from __future__ import annotations

from src.core.models import (
    AndNode,
    EvaluationStatus,
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    ExternalIDs,
    Gene,
    GeneNode,
    GPRNode,
    Metabolite,
    ModelData,
    OrNode,
    Reaction,
    ReactionEvidence,
)


class TestEvidenceStrength:
    def test_values(self):
        assert EvidenceStrength.STRONG.value == 1.0
        assert EvidenceStrength.MODERATE.value == 0.6
        assert EvidenceStrength.WEAK.value == 0.3
        assert EvidenceStrength.ABSENT.value == 0.0

    def test_ordering(self):
        strengths = [EvidenceStrength.ABSENT, EvidenceStrength.STRONG, EvidenceStrength.WEAK]
        sorted_vals = sorted(strengths, key=lambda s: s.value, reverse=True)
        assert sorted_vals[0] == EvidenceStrength.STRONG
        assert sorted_vals[-1] == EvidenceStrength.ABSENT


class TestEvidenceSource:
    def test_values(self):
        assert EvidenceSource.KEGG.value == "kegg"
        assert EvidenceSource.GEMINI.value == "gemini"
        assert EvidenceSource.PERPLEXITY.value == "perplexity"

    def test_all_sources(self):
        assert len(EvidenceSource) == 3


class TestEvaluationStatus:
    def test_values(self):
        assert EvaluationStatus.NOT_EVALUATED.value == "not_evaluated"
        assert EvaluationStatus.IN_PROGRESS.value == "in_progress"
        assert EvaluationStatus.EVALUATED.value == "evaluated"
        assert EvaluationStatus.ERROR.value == "error"


class TestGPRNodes:
    def test_gene_node(self):
        node = GeneNode(gene_id="b0001")
        assert node.gene_id == "b0001"
        assert isinstance(node, GPRNode)

    def test_and_node(self):
        children = [GeneNode("b0001"), GeneNode("b0002")]
        node = AndNode(children=children)
        assert len(node.children) == 2
        assert isinstance(node, GPRNode)

    def test_or_node(self):
        children = [GeneNode("b0001"), GeneNode("b0002")]
        node = OrNode(children=children)
        assert len(node.children) == 2
        assert isinstance(node, GPRNode)

    def test_empty_children_default(self):
        and_node = AndNode()
        or_node = OrNode()
        assert and_node.children == []
        assert or_node.children == []

    def test_nested_tree(self):
        tree = OrNode(
            children=[
                GeneNode("b0001"),
                AndNode(children=[GeneNode("b0002"), GeneNode("b0003")]),
            ]
        )
        assert len(tree.children) == 2
        assert isinstance(tree.children[1], AndNode)


class TestMetabolite:
    def test_basic(self):
        met = Metabolite(id="h2o_c", name="H2O", compartment="c")
        assert met.id == "h2o_c"
        assert met.compartment == "c"

    def test_defaults(self):
        met = Metabolite(id="x", name="X")
        assert met.formula is None
        assert met.charge is None
        assert met.annotation == {}

    def test_annotation(self):
        met = Metabolite(
            id="x",
            name="X",
            annotation={"chebi": ["CHEBI:15377"]},
        )
        assert "chebi" in met.annotation


class TestGene:
    def test_basic(self):
        gene = Gene(id="b2779", name="eno")
        assert gene.id == "b2779"
        assert gene.name == "eno"

    def test_defaults(self):
        gene = Gene(id="b0001")
        assert gene.name is None
        assert gene.annotation == {}


class TestReaction:
    def test_basic(self, sample_reaction):
        assert sample_reaction.id == "ENO"
        assert sample_reaction.name == "enolase"
        assert len(sample_reaction.genes) == 1

    def test_is_exchange(self, exchange_reaction):
        assert exchange_reaction.is_exchange is True

    def test_is_not_exchange(self, sample_reaction):
        assert sample_reaction.is_exchange is False

    def test_is_transport(self):
        rxn = Reaction(
            id="TRP", name="transporter", equation="a -> b", subsystem="Transport, Inner Membrane"
        )
        assert rxn.is_transport is True

    def test_is_not_transport(self, sample_reaction):
        assert sample_reaction.is_transport is False

    def test_has_genes(self, sample_reaction):
        assert sample_reaction.has_genes is True

    def test_has_no_genes(self, exchange_reaction):
        assert exchange_reaction.has_genes is False

    def test_defaults(self):
        rxn = Reaction(id="X", name="X", equation="a -> b")
        assert rxn.subsystem is None
        assert rxn.lower_bound == -1000.0
        assert rxn.upper_bound == 1000.0
        assert rxn.gene_reaction_rule == ""
        assert rxn.gpr_tree is None
        assert rxn.genes == []
        assert rxn.reactants == {}
        assert rxn.products == {}
        assert rxn.annotation == {}


class TestModelData:
    def test_counts(self, sample_model):
        assert sample_model.reaction_count == 3
        assert sample_model.metabolite_count == 5
        assert sample_model.gene_count == 3

    def test_get_reaction(self, sample_model):
        eno = sample_model.get_reaction("ENO")
        assert eno is not None
        assert eno.name == "enolase"

    def test_get_reaction_not_found(self, sample_model):
        assert sample_model.get_reaction("NONEXISTENT") is None

    def test_get_subsystems(self, sample_model):
        subs = sample_model.get_subsystems()
        assert "Glycolysis/Gluconeogenesis" in subs
        assert "Exchange" in subs

    def test_empty_model(self):
        model = ModelData(id="empty", name="Empty")
        assert model.reaction_count == 0
        assert model.metabolite_count == 0
        assert model.gene_count == 0
        assert model.get_subsystems() == []

    def test_cobra_model_default(self):
        model = ModelData(id="test", name="Test")
        assert model.cobra_model is None

    def test_cobra_model_set(self):
        model = ModelData(id="test", name="Test", cobra_model="fake_cobra_model")
        assert model.cobra_model == "fake_cobra_model"

    def test_cobra_model_not_in_repr(self):
        model = ModelData(id="test", name="Test", cobra_model="big_object")
        r = repr(model)
        assert "big_object" not in r


class TestEvidenceItem:
    def test_basic(self):
        item = EvidenceItem(
            source=EvidenceSource.KEGG,
            strength=EvidenceStrength.STRONG,
            description="Test evidence",
        )
        assert item.source == EvidenceSource.KEGG
        assert item.url is None
        assert item.raw_data is None

    def test_with_url(self):
        item = EvidenceItem(
            source=EvidenceSource.KEGG,
            strength=EvidenceStrength.MODERATE,
            description="Found in KEGG",
            url="https://www.kegg.jp/entry/R00658",
        )
        assert item.url == "https://www.kegg.jp/entry/R00658"


class TestReactionEvidence:
    def test_defaults(self):
        ev = ReactionEvidence(reaction_id="RXN1")
        assert ev.confidence_score == 0.0
        assert ev.status == EvaluationStatus.NOT_EVALUATED
        assert ev.items == []
        assert ev.ec_numbers == []
        assert ev.kegg_reaction_ids == []
        assert ev.substrate_match_ratio == 0.0
        assert ev.product_match_ratio == 0.0
        assert ev.gemini_score == 0.0
        assert ev.perplexity_score == 0.0

    def test_kegg_score(self):
        ev = ReactionEvidence(reaction_id="RXN1")
        ev.kegg_score = 0.8
        assert ev.kegg_score == 0.8

    def test_llm_scores(self):
        ev = ReactionEvidence(reaction_id="RXN1")
        ev.gemini_score = 0.9
        ev.perplexity_score = 0.7
        assert ev.gemini_score == 0.9
        assert ev.perplexity_score == 0.7


class TestExternalIDs:
    def test_defaults(self):
        ext = ExternalIDs(reaction_id="ENO")
        assert ext.bigg_id is None
        assert ext.ec_numbers == []
        assert ext.kegg_reaction_ids == []
        assert ext.kegg_substrate_ids == []
        assert ext.kegg_product_ids == []
        assert ext.mnxr_ids == []
