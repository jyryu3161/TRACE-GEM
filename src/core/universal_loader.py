"""Universal metabolic model loader (JSON/SBML).

Loads universal models (e.g., BiGG universal) and extracts candidate reactions
that are not present in a user's model for gap-filling analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cobra

from src.core.cobra_utils import SOLVER_RESERVED_REACTION_IDS, convert_cobra_reaction
from src.core.models import CandidateReaction, ModelData

logger = logging.getLogger("metataskgapfill.universal_loader")

# Prefixes for utility reactions to exclude from candidates
_UTILITY_PREFIXES = ("EX_", "DM_", "SK_", "sink_")
_SOLVER_RESERVED_REACTION_IDS = SOLVER_RESERVED_REACTION_IDS


class UniversalLoader:
    """Load a universal model and extract candidate reactions."""

    def load(self, filepath: str | Path) -> cobra.Model:
        """Auto-detect format by extension and load.

        .json -> load_json()
        .xml, .sbml -> load_sbml()
        """
        filepath = Path(filepath)
        suffix = filepath.suffix.lower()
        if suffix == ".json":
            return self.load_json(filepath)
        if suffix in (".xml", ".sbml"):
            return self.load_sbml(filepath)
        raise ValueError(
            f"Unsupported file format '{suffix}'. Expected .json, .xml, or .sbml."
        )

    def load_json(self, filepath: str | Path) -> cobra.Model:
        """Load a universal model from BiGG JSON format."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Universal model file not found: {filepath}")

        logger.info("Loading universal model (JSON) from %s", filepath)
        model = cobra.io.load_json_model(str(filepath))
        self._remove_solver_reserved_reactions(model)
        logger.info(
            "Loaded universal model '%s': %d reactions, %d metabolites",
            model.id,
            len(model.reactions),
            len(model.metabolites),
        )
        return model

    def load_sbml(self, filepath: str | Path) -> cobra.Model:
        """Load a universal model from SBML/XML format."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Universal model file not found: {filepath}")

        logger.info("Loading universal model (SBML) from %s", filepath)
        model = cobra.io.read_sbml_model(str(filepath))
        self._remove_solver_reserved_reactions(model)
        logger.info(
            "Loaded universal model '%s': %d reactions, %d metabolites",
            model.id,
            len(model.reactions),
            len(model.metabolites),
        )
        return model

    def extract_candidates(
        self,
        universal: cobra.Model,
        user_model: ModelData,
        *,
        exclude_exchange_reactions: bool = True,
    ) -> list[CandidateReaction]:
        """Extract reactions from universal model not present in user model.

        Normalizes IDs (R_ prefix, case-insensitive) and excludes
        exchange/demand/sink utility reactions by default.
        """
        model_ids = self._build_model_reaction_ids(user_model)
        candidates: list[CandidateReaction] = []

        for rxn in universal.reactions:
            if exclude_exchange_reactions and self.is_exchange_or_utility_reaction(rxn.id):
                continue

            normalized = rxn.id.lower()
            normalized_no_prefix = (
                rxn.id[2:].lower() if rxn.id.startswith("R_") else rxn.id.lower()
            )

            if normalized in model_ids or normalized_no_prefix in model_ids:
                continue

            reaction = convert_cobra_reaction(rxn)
            candidates.append(
                CandidateReaction(
                    reaction=reaction,
                    source_model=universal.id or "bigg_universal",
                )
            )

        logger.info(
            "Extracted %d candidate reactions from universal model "
            "(%d total, %d in user model, utility excluded=%s)",
            len(candidates),
            len(universal.reactions),
            len(user_model.reactions),
            exclude_exchange_reactions,
        )
        return candidates

    def _build_model_reaction_ids(self, model: ModelData) -> set[str]:
        """Build normalized set of user model reaction IDs."""
        ids: set[str] = set()
        for rxn in model.reactions:
            ids.add(rxn.id.lower())
            if rxn.id.startswith("R_"):
                ids.add(rxn.id[2:].lower())
            else:
                ids.add(f"R_{rxn.id}".lower())
        return ids

    @staticmethod
    def is_exchange_or_utility_reaction(rxn_id: str) -> bool:
        """Check if reaction is an exchange, demand, or sink reaction."""
        return any(rxn_id.startswith(p) for p in _UTILITY_PREFIXES)

    def _remove_solver_reserved_reactions(self, model: cobra.Model) -> None:
        """Remove reactions whose IDs collide with LP/MPS solver keywords."""
        to_remove = [
            rxn for rxn in model.reactions
            if rxn.id.replace(" ", "").lower() in _SOLVER_RESERVED_REACTION_IDS
        ]
        if not to_remove:
            return
        model.remove_reactions(to_remove, remove_orphans=False)
        logger.warning(
            "Removed %d solver-reserved universal reaction ID(s): %s",
            len(to_remove),
            ", ".join(rxn.id for rxn in to_remove),
        )
