"""Shared utilities for converting COBRApy objects to internal models."""

from __future__ import annotations

import cobra

from src.core.gpr_parser import extract_genes, parse_gpr
from src.core.models import Gene, Metabolite, Reaction


def convert_cobra_reaction(rxn: cobra.Reaction) -> Reaction:
    """Convert a cobra.Reaction to internal Reaction dataclass."""
    gene_rule = rxn.gene_reaction_rule or ""
    genes = extract_genes(gene_rule)
    gpr_tree = parse_gpr(gene_rule)

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
        subsystem=rxn.subsystem or None,
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
