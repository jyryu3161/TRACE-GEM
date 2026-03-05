"""Offline mapping data loader for BiGG ↔ KEGG ID resolution.

Parses files in ./data/ at app startup to build in-memory lookup tables,
eliminating runtime dependency on the BiGG API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("gem_evaluator.mapping_data")

# Default data directory relative to project root
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class MappingData:
    """In-memory ID mapping tables built from ./data/ files."""

    # Metabolite mappings: bigg_universal_model_fixed.json
    met_bigg_to_kegg: dict[str, list[str]] = field(default_factory=dict)
    met_bigg_to_name: dict[str, str] = field(default_factory=dict)

    # Reaction mappings: reac_xref.tsv (BiGG → MNXR → KEGG)
    rxn_bigg_to_kegg: dict[str, list[str]] = field(default_factory=dict)
    rxn_bigg_to_mnxr: dict[str, list[str]] = field(default_factory=dict)
    rxn_kegg_to_bigg: dict[str, list[str]] = field(default_factory=dict)

    # EC number mappings: reaction_analysis_result.tsv
    rxn_ec_to_kegg: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path | None = None) -> MappingData:
        """Load all mapping files from the data directory."""
        data_dir = data_dir or _DATA_DIR
        mapping = cls()

        # Load metabolite mappings
        bigg_model_path = data_dir / "bigg_universal_model_fixed.json"
        if bigg_model_path.exists():
            mapping._load_metabolite_mappings(bigg_model_path)
        else:
            logger.warning("Metabolite mapping file not found: %s", bigg_model_path)

        # Load reaction cross-references
        reac_xref_path = data_dir / "reac_xref.tsv"
        if reac_xref_path.exists():
            mapping._load_reaction_xref(reac_xref_path)
        else:
            logger.warning("Reaction xref file not found: %s", reac_xref_path)

        # Load EC number mappings
        analysis_path = data_dir / "reaction_analysis_result.tsv"
        if analysis_path.exists():
            mapping._load_ec_mappings(analysis_path)
        else:
            logger.warning("Reaction analysis file not found: %s", analysis_path)

        logger.info(
            "Mapping data loaded: %d metabolite mappings, %d reaction mappings, %d EC mappings",
            len(mapping.met_bigg_to_kegg),
            len(mapping.rxn_bigg_to_kegg),
            len(mapping.rxn_ec_to_kegg),
        )
        return mapping

    def _load_metabolite_mappings(self, path: Path) -> None:
        """Parse bigg_universal_model_fixed.json for metabolite BiGG → KEGG mappings."""
        with open(path) as f:
            data = json.load(f)

        for met in data.get("metabolites", []):
            bigg_id = met.get("id", "")
            name = met.get("name", "")
            if not bigg_id:
                continue

            # Strip compartment suffix (e.g., "atp_c" → "atp")
            base_id = self.strip_compartment(bigg_id)

            if name:
                self.met_bigg_to_name[bigg_id] = name
                if base_id != bigg_id:
                    self.met_bigg_to_name.setdefault(base_id, name)

            # Extract KEGG compound IDs from annotation
            annotation = met.get("annotation", {})
            kegg_ids = []
            for key in ("KEGG Compound", "kegg.compound"):
                for uri in annotation.get(key, []):
                    kid = self._extract_id_from_uri(uri)
                    if kid and kid not in kegg_ids:
                        kegg_ids.append(kid)

            if kegg_ids:
                self.met_bigg_to_kegg[bigg_id] = kegg_ids
                # Also store without compartment suffix for flexible lookup
                if base_id != bigg_id:
                    existing = self.met_bigg_to_kegg.get(base_id, [])
                    for kid in kegg_ids:
                        if kid not in existing:
                            existing.append(kid)
                    self.met_bigg_to_kegg[base_id] = existing

    def _load_reaction_xref(self, path: Path) -> None:
        """Parse reac_xref.tsv to build BiGG → MNXR → KEGG reaction mappings."""
        # Two passes: first collect BiGG→MNXR and KEGG→MNXR, then join
        mnxr_to_bigg: dict[str, list[str]] = {}
        mnxr_to_kegg: dict[str, list[str]] = {}

        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue

                source_id = parts[0]
                mnxr_id = parts[1]

                if mnxr_id == "EMPTY":
                    continue

                # Parse bigg.reaction: or biggR: entries
                if source_id.startswith("bigg.reaction:") or source_id.startswith("biggR:"):
                    prefix = (
                        "bigg.reaction:" if source_id.startswith("bigg.reaction:") else "biggR:"
                    )
                    bigg_id = source_id[len(prefix) :]

                    # Skip secondary/obsolete identifiers
                    description = parts[2] if len(parts) > 2 else ""
                    if "secondary/obsolete" in description:
                        continue
                    # Skip R_ prefixed duplicates (use non-prefixed)
                    if bigg_id.startswith("R_"):
                        continue

                    mnxr_to_bigg.setdefault(mnxr_id, [])
                    if bigg_id not in mnxr_to_bigg[mnxr_id]:
                        mnxr_to_bigg[mnxr_id].append(bigg_id)

                    self.rxn_bigg_to_mnxr.setdefault(bigg_id, [])
                    if mnxr_id not in self.rxn_bigg_to_mnxr[bigg_id]:
                        self.rxn_bigg_to_mnxr[bigg_id].append(mnxr_id)

                # Parse keggR: or kegg.reaction: entries
                elif source_id.startswith("keggR:") or source_id.startswith("kegg.reaction:"):
                    prefix = "keggR:" if source_id.startswith("keggR:") else "kegg.reaction:"
                    kegg_id = source_id[len(prefix) :]

                    mnxr_to_kegg.setdefault(mnxr_id, [])
                    if kegg_id not in mnxr_to_kegg[mnxr_id]:
                        mnxr_to_kegg[mnxr_id].append(kegg_id)

        # Join: BiGG → MNXR → KEGG
        for mnxr_id, bigg_ids in mnxr_to_bigg.items():
            kegg_ids = mnxr_to_kegg.get(mnxr_id, [])
            if not kegg_ids:
                continue
            for bigg_id in bigg_ids:
                existing = self.rxn_bigg_to_kegg.get(bigg_id, [])
                for kid in kegg_ids:
                    if kid not in existing:
                        existing.append(kid)
                self.rxn_bigg_to_kegg[bigg_id] = existing

            for kegg_id in kegg_ids:
                existing = self.rxn_kegg_to_bigg.get(kegg_id, [])
                for bid in bigg_ids:
                    if bid not in existing:
                        existing.append(bid)
                self.rxn_kegg_to_bigg[kegg_id] = existing

    def _load_ec_mappings(self, path: Path) -> None:
        """Parse reaction_analysis_result.tsv for EC → MNXR → KEGG mappings."""
        # First collect EC → MNXR, then use rxn_bigg_to_kegg via MNXR
        ec_to_mnxr: dict[str, set[str]] = {}

        with open(path) as f:
            header = True
            for line in f:
                if header:
                    header = False
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue

                ec_raw = parts[0]
                mnxr_id = parts[1]

                # Normalize EC: strip "EC:" prefix if present
                ec = ec_raw.replace("EC:", "").strip()
                if not ec or not mnxr_id:
                    continue

                ec_to_mnxr.setdefault(ec, set()).add(mnxr_id)

        # Map EC → KEGG via shared MNXR IDs
        # We need the MNXR→KEGG mapping built above
        # Rebuild mnxr_to_kegg from rxn_kegg_to_bigg inverse
        # Actually, simpler: iterate rxn_bigg_to_mnxr and rxn_bigg_to_kegg
        mnxr_to_kegg: dict[str, list[str]] = {}
        for bigg_id, mnxr_ids in self.rxn_bigg_to_mnxr.items():
            kegg_ids = self.rxn_bigg_to_kegg.get(bigg_id, [])
            for mnxr_id in mnxr_ids:
                existing = mnxr_to_kegg.get(mnxr_id, [])
                for kid in kegg_ids:
                    if kid not in existing:
                        existing.append(kid)
                mnxr_to_kegg[mnxr_id] = existing

        for ec, ec_mnxr_ids in ec_to_mnxr.items():
            ec_kegg_ids: list[str] = []
            for mnxr_id in ec_mnxr_ids:
                for kid in mnxr_to_kegg.get(mnxr_id, []):
                    if kid not in ec_kegg_ids:
                        ec_kegg_ids.append(kid)
            if ec_kegg_ids:
                self.rxn_ec_to_kegg[ec] = ec_kegg_ids

    @staticmethod
    def strip_compartment(met_id: str) -> str:
        """Strip compartment suffix from metabolite ID (e.g., atp_c → atp)."""
        # BiGG convention: metabolite_compartment (e.g., atp_c, atp_m)
        if "_" in met_id:
            parts = met_id.rsplit("_", 1)
            if len(parts[1]) <= 2:  # compartment codes are 1-2 chars
                return parts[0]
        return met_id

    @staticmethod
    def _extract_id_from_uri(uri: str) -> str:
        """Extract bare ID from identifiers.org URI."""
        if "/" in uri:
            return uri.rsplit("/", 1)[-1]
        return uri
