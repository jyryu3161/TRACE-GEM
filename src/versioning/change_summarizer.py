"""Generate human-readable change summaries."""

from __future__ import annotations

import logging

from src.core.models import ModelDiff
from src.utils.config import Config

logger = logging.getLogger("gem_evaluator.versioning.change_summarizer")


class ChangeSummarizer:
    """Convert a ModelDiff into a natural-language summary.

    Uses deterministic template-based generation.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    async def summarize(self, diff: ModelDiff, change_type: str) -> str:
        """Generate a 1-2 sentence change summary.

        Args:
            diff: The model diff to summarize.
            change_type: One of "initial_load", "gap_fill", "manual_edit", "restore".

        Returns:
            Human-readable summary string.
        """
        return self._template_summary(diff, change_type)

    def _template_summary(self, diff: ModelDiff, change_type: str) -> str:
        """Template-based fallback summary."""
        if change_type == "initial_load":
            return self._initial_load_summary(diff)
        if change_type == "gap_fill":
            return self._gap_fill_summary(diff)
        if change_type == "restore":
            return self._restore_summary(diff)
        if change_type == "manual_edit":
            return self._manual_edit_summary(diff)

        # Generic fallback
        counts = diff.summary_counts
        return f"{change_type}: {counts}" if counts != "No changes" else change_type

    # ------------------------------------------------------------------
    # Template helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _initial_load_summary(diff: ModelDiff) -> str:
        parts = []
        n_rxn = len(diff.reactions_added)
        n_gene = len(diff.genes_added)
        n_met = len(diff.metabolites_added)
        if n_rxn:
            parts.append(f"{n_rxn} reactions")
        if n_gene:
            parts.append(f"{n_gene} genes")
        if n_met:
            parts.append(f"{n_met} metabolites")
        if parts:
            return f"Initial model load ({', '.join(parts)})"
        return "Initial model load"

    @staticmethod
    def _gap_fill_summary(diff: ModelDiff) -> str:
        n_added = len(diff.reactions_added)
        if n_added:
            return f"Gap-filling: added {n_added} reactions"
        return "Gap-filling: no reactions added"

    @staticmethod
    def _restore_summary(diff: ModelDiff) -> str:
        counts = diff.summary_counts
        if counts != "No changes":
            return f"Restored version ({counts})"
        return "Restored version"

    @staticmethod
    def _manual_edit_summary(diff: ModelDiff) -> str:
        modified_ids = sorted({c.reaction_id for c in diff.reactions_modified})
        if modified_ids:
            ids_str = ", ".join(modified_ids[:5])
            if len(modified_ids) > 5:
                ids_str += f" (+{len(modified_ids) - 5} more)"
            return f"Manual edit: modified bounds for {ids_str}"

        parts = []
        if diff.reactions_added:
            parts.append(f"added {len(diff.reactions_added)} reactions")
        if diff.reactions_removed:
            parts.append(f"removed {len(diff.reactions_removed)} reactions")
        if parts:
            return f"Manual edit: {', '.join(parts)}"
        return "Manual edit"
