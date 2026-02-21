"""Tests for DiffEngine."""

from __future__ import annotations

import cobra
import pytest

from src.core.models import ModelDiff, ReactionChange
from src.versioning.diff_engine import DiffEngine


@pytest.fixture
def diff_engine() -> DiffEngine:
    return DiffEngine()


def _make_model(
    reactions: list[dict] | None = None,
    genes: list[str] | None = None,
    metabolites: list[str] | None = None,
) -> cobra.Model:
    """Build a minimal cobra.Model from specs."""
    model = cobra.Model("test")

    # Add metabolites first so reactions can reference them
    met_objects = {}
    for mid in metabolites or []:
        m = cobra.Metabolite(mid, compartment="c")
        met_objects[mid] = m
    if met_objects:
        model.add_metabolites(list(met_objects.values()))

    for rspec in reactions or []:
        rxn = cobra.Reaction(rspec["id"])
        rxn.name = rspec.get("name", "")
        rxn.lower_bound = rspec.get("lower_bound", -1000.0)
        rxn.upper_bound = rspec.get("upper_bound", 1000.0)
        rxn.gene_reaction_rule = rspec.get("gene_reaction_rule", "")
        rxn.subsystem = rspec.get("subsystem", "")
        model.add_reactions([rxn])

    return model


class TestDiffEngineReactions:
    """Tests for reaction add/remove/modify detection."""

    def test_added_reactions(self, diff_engine: DiffEngine) -> None:
        old = _make_model(reactions=[{"id": "R1"}])
        new = _make_model(reactions=[{"id": "R1"}, {"id": "R2"}])

        diff = diff_engine.compute_diff(old, new)

        assert "R2" in diff.reactions_added
        assert diff.reactions_removed == []
        assert diff.reactions_modified == []

    def test_removed_reactions(self, diff_engine: DiffEngine) -> None:
        old = _make_model(reactions=[{"id": "R1"}, {"id": "R2"}])
        new = _make_model(reactions=[{"id": "R1"}])

        diff = diff_engine.compute_diff(old, new)

        assert diff.reactions_added == []
        assert "R2" in diff.reactions_removed
        assert diff.reactions_modified == []

    def test_modified_bounds(self, diff_engine: DiffEngine) -> None:
        old = _make_model(
            reactions=[{"id": "R1", "lower_bound": 0.0, "upper_bound": 1000.0}]
        )
        new = _make_model(
            reactions=[{"id": "R1", "lower_bound": -1000.0, "upper_bound": 500.0}]
        )

        diff = diff_engine.compute_diff(old, new)

        assert diff.reactions_added == []
        assert diff.reactions_removed == []
        assert len(diff.reactions_modified) == 2

        fields = {c.field for c in diff.reactions_modified}
        assert "lower_bound" in fields
        assert "upper_bound" in fields

    def test_modified_gpr(self, diff_engine: DiffEngine) -> None:
        old = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1"}]
        )
        new = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1 or g2"}]
        )

        diff = diff_engine.compute_diff(old, new)

        assert len(diff.reactions_modified) == 1
        change = diff.reactions_modified[0]
        assert change.field == "gene_reaction_rule"
        assert change.old_value == "g1"
        assert change.new_value == "g1 or g2"

    def test_modified_name(self, diff_engine: DiffEngine) -> None:
        old = _make_model(reactions=[{"id": "R1", "name": "Old Name"}])
        new = _make_model(reactions=[{"id": "R1", "name": "New Name"}])

        diff = diff_engine.compute_diff(old, new)

        assert len(diff.reactions_modified) == 1
        assert diff.reactions_modified[0].field == "name"

    def test_modified_subsystem(self, diff_engine: DiffEngine) -> None:
        old = _make_model(reactions=[{"id": "R1", "subsystem": "Glycolysis"}])
        new = _make_model(reactions=[{"id": "R1", "subsystem": "TCA Cycle"}])

        diff = diff_engine.compute_diff(old, new)

        assert len(diff.reactions_modified) == 1
        assert diff.reactions_modified[0].field == "subsystem"


class TestDiffEngineGenes:
    """Tests for gene set diff."""

    def test_genes_added(self, diff_engine: DiffEngine) -> None:
        old = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1"}]
        )
        new = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1 or g2"}]
        )

        diff = diff_engine.compute_diff(old, new)

        assert "g2" in diff.genes_added

    def test_genes_removed(self, diff_engine: DiffEngine) -> None:
        old = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1 or g2"}]
        )
        new = _make_model(
            reactions=[{"id": "R1", "gene_reaction_rule": "g1"}]
        )

        diff = diff_engine.compute_diff(old, new)

        assert "g2" in diff.genes_removed


class TestDiffEngineMetabolites:
    """Tests for metabolite set diff."""

    def test_metabolites_added(self, diff_engine: DiffEngine) -> None:
        old = _make_model(metabolites=["m1"])
        new = _make_model(metabolites=["m1", "m2"])

        diff = diff_engine.compute_diff(old, new)

        assert "m2" in diff.metabolites_added

    def test_metabolites_removed(self, diff_engine: DiffEngine) -> None:
        old = _make_model(metabolites=["m1", "m2"])
        new = _make_model(metabolites=["m1"])

        diff = diff_engine.compute_diff(old, new)

        assert "m2" in diff.metabolites_removed


class TestDiffEngineEmpty:
    """Tests for empty / no-change scenarios."""

    def test_identical_models(self, diff_engine: DiffEngine) -> None:
        model_spec = [
            {"id": "R1", "name": "rxn1", "lower_bound": 0.0, "upper_bound": 1000.0}
        ]
        old = _make_model(reactions=model_spec, metabolites=["m1"])
        new = _make_model(reactions=model_spec, metabolites=["m1"])

        diff = diff_engine.compute_diff(old, new)

        assert diff.is_empty

    def test_both_empty_models(self, diff_engine: DiffEngine) -> None:
        old = _make_model()
        new = _make_model()

        diff = diff_engine.compute_diff(old, new)

        assert diff.is_empty

    def test_summary_counts_no_changes(self, diff_engine: DiffEngine) -> None:
        diff = ModelDiff()
        assert diff.summary_counts == "No changes"

    def test_summary_counts_with_changes(self, diff_engine: DiffEngine) -> None:
        diff = ModelDiff(
            reactions_added=["R1", "R2"],
            reactions_removed=["R3"],
            reactions_modified=[
                ReactionChange("R4", "name", "old", "new"),
            ],
            genes_added=["g1"],
        )
        summary = diff.summary_counts
        assert "+2 reactions" in summary
        assert "-1 reactions" in summary
        assert "~1 modified" in summary
        assert "+1 genes" in summary
