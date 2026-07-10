"""Shared utilities for converting COBRApy objects to internal models."""

from __future__ import annotations

import logging

import cobra

from src.core.gpr_parser import extract_genes, parse_gpr
from src.core.models import Gene, Metabolite, ModelData, Reaction

logger = logging.getLogger("metataskgapfill.cobra_utils")

# Reaction IDs that collide with LP/MPS solver-format keywords. A reaction
# whose ID lowercases to one of these (e.g. CarveMe's ``St``) optimizes fine
# in memory but corrupts any LP-text round-trip the solver performs
# (model.copy()/clone, snapshots), so they must be renamed or removed.
SOLVER_RESERVED_REACTION_IDS = frozenset(
    {
        "bounds",
        "binaries",
        "binary",
        "end",
        "generals",
        "general",
        "maximize",
        "maximise",
        "minimize",
        "minimise",
        "st",
        "subject",
        "subjectto",
    }
)


def is_solver_reserved_id(rxn_id: str) -> bool:
    """Return True if ``rxn_id`` collides with an LP/MPS solver keyword."""
    return rxn_id.replace(" ", "").lower() in SOLVER_RESERVED_REACTION_IDS


def rename_solver_reserved_reactions(model: cobra.Model) -> list[tuple[str, str]]:
    """Rename reactions whose IDs collide with solver-format keywords.

    Used for user/built models (e.g. CarveMe output) where the reaction is
    meaningful and must be preserved — unlike universal models, where such IDs
    are dropped. Returns the list of ``(old_id, new_id)`` renames applied.
    """
    existing = set(model.reactions.list_attr("id"))
    renames: list[tuple[str, str]] = []
    for rxn in list(model.reactions):
        if not is_solver_reserved_id(rxn.id):
            continue
        base = f"{rxn.id}_rxn"
        new_id = base
        suffix = 1
        while new_id in existing:
            new_id = f"{base}{suffix}"
            suffix += 1
        old_id = rxn.id
        existing.discard(old_id)
        existing.add(new_id)
        rxn.id = new_id
        renames.append((old_id, new_id))
    if renames:
        model.repair()
        logger.warning(
            "Renamed %d solver-reserved reaction ID(s): %s",
            len(renames),
            ", ".join(f"{o}->{n}" for o, n in renames),
        )
    return renames


def convert_cobra_reaction(rxn: cobra.Reaction) -> Reaction:
    """Convert a cobra.Reaction to internal Reaction dataclass."""
    gene_rule = rxn.gene_reaction_rule or ""
    genes = extract_genes(gene_rule)
    gpr_tree = parse_gpr(gene_rule)
    subsystem = rxn.subsystem or rxn.notes.get("SUBSYSTEM") or None

    reactants: dict[str, float] = {}
    products: dict[str, float] = {}
    for met, coef in rxn.metabolites.items():
        if coef < 0:
            reactants[met.id] = abs(coef)
        else:
            products[met.id] = coef

    annotation = normalize_annotation(rxn.annotation)

    return Reaction(
        id=rxn.id,
        name=rxn.name or rxn.id,
        equation=rxn.build_reaction_string(use_metabolite_names=True),
        equation_id=rxn.build_reaction_string(use_metabolite_names=False),
        subsystem=subsystem,
        lower_bound=rxn.lower_bound,
        upper_bound=rxn.upper_bound,
        gene_reaction_rule=gene_rule,
        gpr_tree=gpr_tree,
        genes=genes,
        reactants=reactants,
        products=products,
        annotation=annotation,
    )


def convert_cobra_metabolite(met: cobra.Metabolite) -> Metabolite:
    """Convert a cobra.Metabolite to internal Metabolite dataclass."""
    return Metabolite(
        id=met.id,
        name=met.name or met.id,
        formula=met.formula or None,
        compartment=met.compartment or None,
        charge=met.charge if hasattr(met, "charge") else None,
        annotation=normalize_annotation(met.annotation),
    )


def convert_cobra_gene(gene: cobra.Gene) -> Gene:
    """Convert a cobra.Gene to internal Gene dataclass."""
    return Gene(
        id=gene.id,
        name=gene.name or None,
        annotation=normalize_annotation(gene.annotation),
    )


def sync_model_data_from_cobra(
    model_data: ModelData,
    cobra_model: cobra.Model,
) -> ModelData:
    """Refresh internal ModelData lists from a COBRA model in place."""
    model_data.id = cobra_model.id
    model_data.name = cobra_model.name or cobra_model.id
    model_data.reactions = [convert_cobra_reaction(r) for r in cobra_model.reactions]
    model_data.metabolites = [convert_cobra_metabolite(m) for m in cobra_model.metabolites]
    model_data.genes = [convert_cobra_gene(g) for g in cobra_model.genes]
    model_data.cobra_model = cobra_model
    model_data._reaction_index = {r.id: r for r in model_data.reactions}
    return model_data


def normalize_annotation(annotation: dict) -> dict[str, list[str]]:
    """Normalize COBRApy annotation dict to {db: [ids]}."""
    result: dict[str, list[str]] = {}
    if not annotation:
        return result
    for key, value in annotation.items():
        if isinstance(value, str):
            result[key] = [value]
        elif isinstance(value, list):
            result[key] = [str(v) for v in value]
        else:
            result[key] = [str(value)]
    return result
