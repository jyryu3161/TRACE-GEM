"""Identifier mapper: resolves BiGG reaction IDs to KEGG IDs via offline mapping."""

from __future__ import annotations

import logging

from src.core.mapping_data import MappingData
from src.core.models import ExternalIDs, Reaction

logger = logging.getLogger("metataskgapfill.id_mapper")


class IdentifierMapper:
    """Maps BiGG model reaction/metabolite IDs to KEGG IDs using offline data.

    Uses pre-loaded MappingData (from ./data/ files) instead of runtime API calls.
    """

    def __init__(self, mapping_data: MappingData) -> None:
        self._mapping = mapping_data

    async def resolve(self, reaction: Reaction, *, universal: bool = False) -> ExternalIDs:
        """Resolve a reaction's external IDs via offline mapping.

        Args:
            reaction: The reaction to resolve IDs for.
            universal: If True, use universal-model annotation keys
                (e.g., "KEGG Reaction" vs "kegg.reaction"). Metabolite→KEGG
                mapping runs for both cases so universal gap-fill candidates can
                be metabolite-reconciled (they carry BiGG metabolite IDs like
                ``prpp_c`` that resolve via ``met_bigg_to_kegg``).
        """
        bigg_id = self._normalize_bigg_id(reaction.id)
        ext = ExternalIDs(reaction_id=reaction.id, bigg_id=bigg_id)

        # 1. Extract from annotation (format depends on universal flag)
        if universal:
            self._extract_from_universal_annotation(reaction, ext)
        else:
            self._extract_from_annotation(reaction, ext)

        # 2. BiGG reaction ID → KEGG reaction IDs (offline mapping)
        kegg_rxn_ids = self._mapping.rxn_bigg_to_kegg.get(bigg_id, [])
        for kid in kegg_rxn_ids:
            if kid not in ext.kegg_reaction_ids:
                ext.kegg_reaction_ids.append(kid)

        # 3. MNXR IDs for reference
        mnxr_ids = self._mapping.rxn_bigg_to_mnxr.get(bigg_id, [])
        ext.mnxr_ids.extend(mnxr_ids)

        # 4. EC number → KEGG reaction IDs (supplementary)
        for ec in ext.ec_numbers:
            ec_kegg_ids = self._mapping.rxn_ec_to_kegg.get(ec, [])
            for kid in ec_kegg_ids:
                if kid not in ext.kegg_reaction_ids:
                    ext.kegg_reaction_ids.append(kid)

        # 5-6. Map metabolites to KEGG compound IDs. Runs for universal
        # candidates too so they can be metabolite-reconciled during gap-fill.
        ext.kegg_stoichiometry_complete = True
        for met_id, coefficient in reaction.reactants.items():
            kegg_ids = self._resolve_metabolite_kegg(met_id)
            if len(kegg_ids) != 1:
                ext.kegg_stoichiometry_complete = False
            for kid in kegg_ids:
                if kid not in ext.kegg_substrate_ids:
                    ext.kegg_substrate_ids.append(kid)
            if len(kegg_ids) == 1:
                kid = kegg_ids[0]
                ext.kegg_substrate_stoichiometry[kid] = ext.kegg_substrate_stoichiometry.get(
                    kid, 0.0
                ) + abs(float(coefficient))

        for met_id, coefficient in reaction.products.items():
            kegg_ids = self._resolve_metabolite_kegg(met_id)
            if len(kegg_ids) != 1:
                ext.kegg_stoichiometry_complete = False
            for kid in kegg_ids:
                if kid not in ext.kegg_product_ids:
                    ext.kegg_product_ids.append(kid)
            if len(kegg_ids) == 1:
                kid = kegg_ids[0]
                ext.kegg_product_stoichiometry[kid] = ext.kegg_product_stoichiometry.get(
                    kid, 0.0
                ) + abs(float(coefficient))

        return ext

    def get_metabolite_kegg_id(self, met_id: str) -> str | None:
        """Get the first KEGG compound ID for a metabolite, or None."""
        ids = self._resolve_metabolite_kegg(met_id)
        return ids[0] if ids else None

    def get_metabolite_name(self, met_id: str) -> str | None:
        """Get metabolite name from mapping data."""
        name = self._mapping.met_bigg_to_name.get(met_id)
        if name:
            return name
        base_id = MappingData.strip_compartment(met_id)
        return self._mapping.met_bigg_to_name.get(base_id)

    def _resolve_metabolite_kegg(self, met_id: str) -> list[str]:
        """Resolve a metabolite BiGG ID to KEGG compound IDs."""
        # Try exact match first
        kegg_ids = self._mapping.met_bigg_to_kegg.get(met_id, [])
        if kegg_ids:
            return kegg_ids

        # Try without compartment suffix
        base_id = MappingData.strip_compartment(met_id)
        return self._mapping.met_bigg_to_kegg.get(base_id, [])

    def _normalize_bigg_id(self, reaction_id: str) -> str:
        """Normalize COBRApy reaction ID to BiGG format."""
        rid = reaction_id
        if rid.startswith("R_"):
            rid = rid[2:]
        # Decode COBRApy SBML encoding
        rid = rid.replace("__LPAREN__", "(")
        rid = rid.replace("__RPAREN__", ")")
        rid = rid.replace("__DASH__", "-")
        rid = rid.replace("_DASH_", "-")
        rid = rid.replace("_LPAREN_", "(")
        rid = rid.replace("_RPAREN_", ")")
        return rid

    def _extract_from_annotation(self, reaction: Reaction, ext: ExternalIDs) -> None:
        """Extract external IDs from SBML annotation if available."""
        ann = reaction.annotation

        for key in ("ec-code", "ec_number", "EC Number"):
            if key in ann:
                for val in ann[key]:
                    ec = self._extract_id_from_uri(val)
                    if ec not in ext.ec_numbers:
                        ext.ec_numbers.append(ec)

        for key in ("kegg.reaction", "KEGG Reaction"):
            if key in ann:
                for val in ann[key]:
                    kid = self._extract_id_from_uri(val)
                    if kid not in ext.kegg_reaction_ids:
                        ext.kegg_reaction_ids.append(kid)

    async def resolve_universal(self, reaction: Reaction) -> ExternalIDs:
        """Resolve external IDs for a universal model reaction.

        Convenience wrapper around resolve(universal=True).
        """
        return await self.resolve(reaction, universal=True)

    def _extract_from_universal_annotation(self, reaction: Reaction, ext: ExternalIDs) -> None:
        """Extract external IDs from universal model annotation.

        Supports annotation keys used by BiGG universal model:
        - "KEGG Reaction" -> kegg_reaction_ids
        - "EC Number" -> ec_numbers
        - "MetaNetX (MNX) Equation" -> mnxr_ids -> kegg (via mapping)
        """
        ann = reaction.annotation

        for key in ("KEGG Reaction", "kegg.reaction"):
            if key in ann:
                for val in ann[key]:
                    kid = self._extract_id_from_uri(val)
                    if kid not in ext.kegg_reaction_ids:
                        ext.kegg_reaction_ids.append(kid)

        for key in ("EC Number", "ec-code", "ec_number"):
            if key in ann:
                for val in ann[key]:
                    ec = self._extract_id_from_uri(val)
                    if ec not in ext.ec_numbers:
                        ext.ec_numbers.append(ec)

        if "MetaNetX (MNX) Equation" in ann:
            for val in ann["MetaNetX (MNX) Equation"]:
                mnxr_id = self._extract_id_from_uri(val)
                if mnxr_id not in ext.mnxr_ids:
                    ext.mnxr_ids.append(mnxr_id)

    @staticmethod
    def _extract_id_from_uri(uri: str) -> str:
        """Extract bare ID from identifiers.org URI or similar."""
        if "/" in uri:
            return uri.rsplit("/", 1)[-1]
        return uri
