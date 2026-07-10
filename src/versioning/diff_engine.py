"""Compute diffs between two cobra.Model instances."""

from __future__ import annotations

import json
import logging

import cobra

from src.core.models import EntityChange, ModelDiff, ReactionChange

logger = logging.getLogger("metataskgapfill.versioning.diff_engine")


class DiffEngine:
    """Compare two cobra.Model instances and produce a ModelDiff."""

    def compute_diff(self, old_model: cobra.Model, new_model: cobra.Model) -> ModelDiff:
        """Compare two models and return a ModelDiff.

        Comparison:
        1. Reactions: ID set diff for added/removed
        2. Shared reactions: compare bounds, GPR, name, subsystem
        3. Genes: ID set diff
        4. Metabolites: ID set diff
        """
        old_rxns = {r.id: r for r in old_model.reactions}
        new_rxns = {r.id: r for r in new_model.reactions}

        added, removed, modified = self._compare_reactions(old_rxns, new_rxns)

        old_gene_ids = {g.id for g in old_model.genes}
        new_gene_ids = {g.id for g in new_model.genes}

        old_met_ids = {m.id for m in old_model.metabolites}
        new_met_ids = {m.id for m in new_model.metabolites}
        entity_changes = self._compare_model_fields(old_model, new_model)
        entity_changes.extend(
            self._compare_entity_fields(
                "metabolite",
                {m.id: m for m in old_model.metabolites},
                {m.id: m for m in new_model.metabolites},
                ("name", "formula", "charge", "compartment", "annotation"),
            )
        )
        entity_changes.extend(
            self._compare_entity_fields(
                "gene",
                {g.id: g for g in old_model.genes},
                {g.id: g for g in new_model.genes},
                ("name", "annotation"),
            )
        )

        diff = ModelDiff(
            reactions_added=sorted(added),
            reactions_removed=sorted(removed),
            reactions_modified=modified,
            genes_added=sorted(new_gene_ids - old_gene_ids),
            genes_removed=sorted(old_gene_ids - new_gene_ids),
            metabolites_added=sorted(new_met_ids - old_met_ids),
            metabolites_removed=sorted(old_met_ids - new_met_ids),
            entity_changes=entity_changes,
        )

        logger.debug(
            "Diff computed: %s",
            diff.summary_counts,
        )
        return diff

    def _compare_reactions(
        self,
        old_rxns: dict[str, cobra.Reaction],
        new_rxns: dict[str, cobra.Reaction],
    ) -> tuple[list[str], list[str], list[ReactionChange]]:
        """Compare reactions by ID and field values.

        Returns:
            (added_ids, removed_ids, modifications)
        """
        old_ids = set(old_rxns.keys())
        new_ids = set(new_rxns.keys())

        added = list(new_ids - old_ids)
        removed = list(old_ids - new_ids)

        modified: list[ReactionChange] = []
        for rxn_id in old_ids & new_ids:
            changes = self._diff_reaction(old_rxns[rxn_id], new_rxns[rxn_id])
            modified.extend(changes)

        return added, removed, modified

    def _diff_reaction(self, old: cobra.Reaction, new: cobra.Reaction) -> list[ReactionChange]:
        """Detect field changes for a single reaction.

        Compared fields: lower_bound, upper_bound, gene_reaction_rule, name, subsystem.
        """
        changes: list[ReactionChange] = []
        fields = [
            ("lower_bound", str(old.lower_bound), str(new.lower_bound)),
            ("upper_bound", str(old.upper_bound), str(new.upper_bound)),
            (
                "gene_reaction_rule",
                old.gene_reaction_rule or "",
                new.gene_reaction_rule or "",
            ),
            ("name", old.name or "", new.name or ""),
            ("subsystem", old.subsystem or "", new.subsystem or ""),
            ("stoichiometry", self._stoichiometry(old), self._stoichiometry(new)),
            ("annotation", self._canonical(old.annotation), self._canonical(new.annotation)),
            (
                "objective_coefficient",
                str(old.objective_coefficient),
                str(new.objective_coefficient),
            ),
        ]
        for field_name, old_val, new_val in fields:
            if old_val != new_val:
                changes.append(
                    ReactionChange(
                        reaction_id=old.id,
                        field=field_name,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )
        return changes

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _stoichiometry(cls, reaction: cobra.Reaction) -> str:
        return cls._canonical(
            {metabolite.id: coefficient for metabolite, coefficient in reaction.metabolites.items()}
        )

    @classmethod
    def _compare_entity_fields(
        cls,
        entity_type: str,
        old_entities: dict[str, object],
        new_entities: dict[str, object],
        fields: tuple[str, ...],
    ) -> list[EntityChange]:
        changes: list[EntityChange] = []
        for entity_id in sorted(old_entities.keys() & new_entities.keys()):
            old = old_entities[entity_id]
            new = new_entities[entity_id]
            for field_name in fields:
                old_value = cls._canonical(getattr(old, field_name, None))
                new_value = cls._canonical(getattr(new, field_name, None))
                if old_value != new_value:
                    changes.append(
                        EntityChange(entity_type, entity_id, field_name, old_value, new_value)
                    )
        return changes

    @classmethod
    def _compare_model_fields(
        cls, old_model: cobra.Model, new_model: cobra.Model
    ) -> list[EntityChange]:
        old_objective = {
            reaction.id: reaction.objective_coefficient
            for reaction in old_model.reactions
            if reaction.objective_coefficient
        }
        new_objective = {
            reaction.id: reaction.objective_coefficient
            for reaction in new_model.reactions
            if reaction.objective_coefficient
        }
        fields = (
            ("id", old_model.id, new_model.id),
            ("name", old_model.name, new_model.name),
            ("objective", old_objective, new_objective),
            (
                "objective_direction",
                old_model.objective.direction,
                new_model.objective.direction,
            ),
        )
        return [
            EntityChange(
                "model", old_model.id, field_name, cls._canonical(old), cls._canonical(new)
            )
            for field_name, old, new in fields
            if cls._canonical(old) != cls._canonical(new)
        ]
