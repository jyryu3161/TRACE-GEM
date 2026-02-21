"""SBML model parser using COBRApy."""

from __future__ import annotations

import logging
from pathlib import Path

import cobra

from src.core.gpr_parser import extract_genes, parse_gpr
from src.core.models import Gene, Metabolite, ModelData, Reaction
from src.utils.constants import KEGG_CODE_TO_NAME, ORGANISM_MAP

logger = logging.getLogger("gem_evaluator.sbml_parser")


class SBMLParser:
    """Parse SBML XML files into ModelData using COBRApy."""

    def load_model(self, filepath: str | Path) -> ModelData:
        """Load an SBML model and convert to internal ModelData format."""
        import warnings

        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"SBML file not found: {filepath}")

        logger.info("Loading SBML model from %s", filepath)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cobra_model = cobra.io.read_sbml_model(str(filepath))
        logger.info(
            "Loaded model '%s': %d reactions, %d metabolites, %d genes",
            cobra_model.id,
            len(cobra_model.reactions),
            len(cobra_model.metabolites),
            len(cobra_model.genes),
        )

        model_data = self._convert_model(cobra_model)
        model_data.cobra_model = cobra_model
        self._detect_organism(model_data)
        return model_data

    def _convert_model(self, cobra_model: cobra.Model) -> ModelData:
        reactions = [self._convert_reaction(r) for r in cobra_model.reactions]
        metabolites = [self._convert_metabolite(m) for m in cobra_model.metabolites]
        genes = [self._convert_gene(g) for g in cobra_model.genes]

        return ModelData(
            id=cobra_model.id,
            name=cobra_model.name or cobra_model.id,
            reactions=reactions,
            metabolites=metabolites,
            genes=genes,
        )

    def _convert_reaction(self, rxn: cobra.Reaction) -> Reaction:
        gene_rule = rxn.gene_reaction_rule or ""
        genes = extract_genes(gene_rule)
        gpr_tree = parse_gpr(gene_rule)

        reactants = {}
        products = {}
        for met, coef in rxn.metabolites.items():
            if coef < 0:
                reactants[met.id] = abs(coef)
            else:
                products[met.id] = coef

        annotation = self._normalize_annotation(rxn.annotation)

        return Reaction(
            id=rxn.id,
            name=rxn.name or rxn.id,
            equation=rxn.build_reaction_string(use_metabolite_names=True),
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

    def _convert_metabolite(self, met: cobra.Metabolite) -> Metabolite:
        return Metabolite(
            id=met.id,
            name=met.name or met.id,
            formula=met.formula or None,
            compartment=met.compartment or None,
            charge=met.charge if hasattr(met, "charge") else None,
            annotation=self._normalize_annotation(met.annotation),
        )

    def _convert_gene(self, gene: cobra.Gene) -> Gene:
        return Gene(
            id=gene.id,
            name=gene.name or None,
            annotation=self._normalize_annotation(gene.annotation),
        )

    def _normalize_annotation(self, annotation: dict) -> dict[str, list[str]]:
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

    def _detect_organism(self, model: ModelData) -> None:
        """Auto-detect organism from model ID."""
        model_id = model.id

        # Check known model ID patterns
        for prefix, kegg_code in ORGANISM_MAP.items():
            if model_id.startswith(prefix) or prefix in model_id:
                model.kegg_organism_code = kegg_code
                model.organism = self._kegg_code_to_name(kegg_code)
                logger.info(
                    "Auto-detected organism: %s (KEGG: %s)",
                    model.organism,
                    kegg_code,
                )
                return

        # Try to extract from model name
        name_lower = (model.name or "").lower()
        if "coli" in name_lower or "escherichia" in name_lower:
            model.kegg_organism_code = "eco"
            model.organism = "Escherichia coli"
        elif "cerevisiae" in name_lower or "yeast" in name_lower:
            model.kegg_organism_code = "sce"
            model.organism = "Saccharomyces cerevisiae"
        elif "sapiens" in name_lower or "human" in name_lower:
            model.kegg_organism_code = "hsa"
            model.organism = "Homo sapiens"
        else:
            logger.warning(
                "Could not auto-detect organism for model '%s'. "
                "Please set organism manually in Settings.",
                model_id,
            )

    def _kegg_code_to_name(self, code: str) -> str:
        return KEGG_CODE_TO_NAME.get(code, code)
