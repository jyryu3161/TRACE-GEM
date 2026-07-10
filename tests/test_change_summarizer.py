"""Tests for ChangeSummarizer."""

from __future__ import annotations

import pytest

from src.core.models import ModelDiff, ReactionChange
from src.utils.config import Config
from src.versioning.change_summarizer import ChangeSummarizer


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def summarizer(config: Config) -> ChangeSummarizer:
    return ChangeSummarizer(config)


class TestTemplateSummary:
    """Template-based summary generation."""

    def test_initial_load(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(
            reactions_added=[f"RXN{i}" for i in range(10)],
            genes_added=[f"g{i}" for i in range(5)],
            metabolites_added=[f"m{i}" for i in range(8)],
        )
        result = summarizer._template_summary(diff, "initial_load")
        assert "Initial model load" in result
        assert "10 reactions" in result
        assert "5 genes" in result
        assert "8 metabolites" in result

    def test_initial_load_empty(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff()
        result = summarizer._template_summary(diff, "initial_load")
        assert result == "Initial model load"

    def test_gap_fill(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["GLNS", "PRPPS", "GAPD"])
        result = summarizer._template_summary(diff, "gap_fill")
        assert "Gap-filling" in result
        assert "3 reactions" in result

    def test_gap_fill_no_additions(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff()
        result = summarizer._template_summary(diff, "gap_fill")
        assert "no reactions added" in result

    def test_manual_edit_with_modifications(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(
            reactions_modified=[
                ReactionChange("PFK", "lower_bound", "0.0", "-1000.0"),
                ReactionChange("PGK", "upper_bound", "1000.0", "500.0"),
            ]
        )
        result = summarizer._template_summary(diff, "manual_edit")
        assert "Manual edit" in result
        assert "PFK" in result
        assert "PGK" in result

    def test_manual_edit_many_modifications(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(
            reactions_modified=[
                ReactionChange(f"RXN{i}", "lower_bound", "0", "1") for i in range(8)
            ]
        )
        result = summarizer._template_summary(diff, "manual_edit")
        assert "Manual edit" in result
        assert "+3 more" in result

    def test_manual_edit_with_additions(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["NEW_RXN"])
        result = summarizer._template_summary(diff, "manual_edit")
        assert "Manual edit" in result
        assert "added 1 reactions" in result

    def test_manual_edit_empty(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff()
        result = summarizer._template_summary(diff, "manual_edit")
        assert result == "Manual edit"

    def test_restore(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["RXN1"], reactions_removed=["RXN2"])
        result = summarizer._template_summary(diff, "restore")
        assert "Restored version" in result

    def test_restore_no_changes(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff()
        result = summarizer._template_summary(diff, "restore")
        assert result == "Restored version"

    def test_unknown_change_type(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["RXN1"])
        result = summarizer._template_summary(diff, "custom_type")
        assert "custom_type" in result

    def test_unknown_change_type_no_changes(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff()
        result = summarizer._template_summary(diff, "custom_type")
        assert result == "custom_type"


class TestSummarizeAsync:
    """Async summarize() method."""

    async def test_uses_template(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["RXN1", "RXN2"])
        result = await summarizer.summarize(diff, "gap_fill")
        assert "Gap-filling" in result
        assert "2 reactions" in result
