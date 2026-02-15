"""Tests for GPR parser."""

from src.core.gpr_parser import extract_genes, gpr_to_string, parse_gpr
from src.core.models import AndNode, GeneNode, OrNode


class TestParseGPR:
    def test_empty_string(self):
        assert parse_gpr("") is None
        assert parse_gpr("  ") is None
        assert parse_gpr(None) is None

    def test_single_gene(self):
        node = parse_gpr("b2779")
        assert isinstance(node, GeneNode)
        assert node.gene_id == "b2779"

    def test_and_expression(self):
        node = parse_gpr("b0726 and b0727")
        assert isinstance(node, AndNode)
        assert len(node.children) == 2
        assert all(isinstance(c, GeneNode) for c in node.children)
        assert node.children[0].gene_id == "b0726"
        assert node.children[1].gene_id == "b0727"

    def test_or_expression(self):
        node = parse_gpr("b0726 or b0727")
        assert isinstance(node, OrNode)
        assert len(node.children) == 2

    def test_nested_expression(self):
        node = parse_gpr("b0726 or (b0727 and b0728)")
        assert isinstance(node, OrNode)
        assert len(node.children) == 2
        assert isinstance(node.children[0], GeneNode)
        assert isinstance(node.children[1], AndNode)

    def test_complex_expression(self):
        node = parse_gpr("(b0726 and b0727) or (b0728 and b0729)")
        assert isinstance(node, OrNode)
        assert len(node.children) == 2
        assert all(isinstance(c, AndNode) for c in node.children)

    def test_triple_or(self):
        node = parse_gpr("b0001 or b0002 or b0003")
        assert isinstance(node, OrNode)
        assert len(node.children) == 3


class TestExtractGenes:
    def test_empty(self):
        assert extract_genes("") == []
        assert extract_genes(None) == []

    def test_single(self):
        assert extract_genes("b2779") == ["b2779"]

    def test_multiple(self):
        genes = extract_genes("b0726 and b0727 or b0728")
        assert sorted(genes) == ["b0726", "b0727", "b0728"]

    def test_dedup(self):
        genes = extract_genes("b0001 or b0001")
        assert genes == ["b0001"]


class TestGPRToString:
    def test_none(self):
        assert gpr_to_string(None) == ""

    def test_single(self):
        assert gpr_to_string(GeneNode("b2779")) == "b2779"

    def test_and(self):
        node = AndNode([GeneNode("a"), GeneNode("b")])
        assert gpr_to_string(node) == "(a and b)"

    def test_or(self):
        node = OrNode([GeneNode("a"), GeneNode("b")])
        assert gpr_to_string(node) == "(a or b)"
