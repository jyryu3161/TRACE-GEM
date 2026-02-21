"""Tests for ChangeSummarizer."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import ModelDiff, ReactionChange
from src.utils.config import Config
from src.versioning.change_summarizer import ChangeSummarizer


@pytest.fixture
def config() -> Config:
    return Config(gemini_api_key=None)


@pytest.fixture
def summarizer(config: Config) -> ChangeSummarizer:
    return ChangeSummarizer(config)


class TestTemplateSummary:
    """Template-based summary generation (no LLM)."""

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
                ReactionChange(f"RXN{i}", "lower_bound", "0", "1")
                for i in range(8)
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

    async def test_uses_template_when_no_api_key(self, summarizer: ChangeSummarizer) -> None:
        diff = ModelDiff(reactions_added=["RXN1", "RXN2"])
        result = await summarizer.summarize(diff, "gap_fill")
        assert "Gap-filling" in result
        assert "2 reactions" in result

    async def test_llm_fallback_on_error(self) -> None:
        config = Config(gemini_api_key="fake-key")
        summarizer = ChangeSummarizer(config)
        diff = ModelDiff(reactions_added=["RXN1"])

        with patch.object(
            summarizer, "_llm_summary", side_effect=RuntimeError("API error")
        ):
            result = await summarizer.summarize(diff, "gap_fill")
            assert "Gap-filling" in result

    async def test_llm_called_when_key_present(self) -> None:
        config = Config(gemini_api_key="fake-key")
        summarizer = ChangeSummarizer(config)
        diff = ModelDiff(reactions_added=["RXN1"])

        with patch.object(
            summarizer, "_llm_summary", new_callable=AsyncMock, return_value="LLM summary"
        ) as mock_llm:
            result = await summarizer.summarize(diff, "gap_fill")
            assert result == "LLM summary"
            mock_llm.assert_awaited_once_with(diff, "gap_fill")

    async def test_llm_summary_builds_prompt(self) -> None:
        """Verify _llm_summary calls Gemini with a proper prompt."""
        config = Config(gemini_api_key="test-key")
        summarizer = ChangeSummarizer(config)
        diff = ModelDiff(
            reactions_added=["GLNS", "PRPPS"],
            reactions_modified=[
                ReactionChange("PFK", "lower_bound", "0", "1"),
            ],
        )

        mock_response = MagicMock()
        mock_response.text = "Added 2 reactions and modified PFK bounds."
        mock_client_instance = MagicMock()
        mock_client_instance.models.generate_content.return_value = mock_response

        mock_genai_module = MagicMock()
        mock_genai_module.Client.return_value = mock_client_instance

        # Pre-insert mock into sys.modules so `from google import genai` resolves
        mock_google = MagicMock()
        mock_google.genai = mock_genai_module
        saved_google = sys.modules.get("google")
        saved_genai = sys.modules.get("google.genai")
        sys.modules["google"] = mock_google
        sys.modules["google.genai"] = mock_genai_module
        try:
            result = await summarizer._llm_summary(diff, "gap_fill")
        finally:
            if saved_google is not None:
                sys.modules["google"] = saved_google
            else:
                sys.modules.pop("google", None)
            if saved_genai is not None:
                sys.modules["google.genai"] = saved_genai
            else:
                sys.modules.pop("google.genai", None)

        assert result == "Added 2 reactions and modified PFK bounds."
        mock_client_instance.models.generate_content.assert_called_once()
        call_args = mock_client_instance.models.generate_content.call_args
        prompt = call_args.kwargs.get("contents", call_args[1].get("contents", ""))
        assert "gap_fill" in prompt
        assert "GLNS" in prompt

    async def test_llm_empty_response_falls_back(self) -> None:
        """When LLM returns empty text, summarize() falls back to template."""
        config = Config(gemini_api_key="test-key")
        summarizer = ChangeSummarizer(config)
        diff = ModelDiff()

        # Mock _llm_summary to raise ValueError (as empty response does)
        with patch.object(
            summarizer, "_llm_summary", side_effect=ValueError("Empty LLM response")
        ):
            result = await summarizer.summarize(diff, "initial_load")
            assert "Initial model load" in result
