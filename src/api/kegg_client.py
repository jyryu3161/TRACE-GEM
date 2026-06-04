"""KEGG API client with reaction parsing and 3-stage verification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.api.base_client import BaseAPIClient
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)
from src.utils.constants import KEGG_API_BASE, RATE_LIMITS

logger = logging.getLogger("metataskgapfill.api.kegg")


@dataclass
class KEGGReactionData:
    """Parsed KEGG reaction entry."""

    entry_id: str = ""
    name: str = ""
    definition: str = ""
    equation: str = ""
    enzyme: list[str] = field(default_factory=list)
    is_reversible: bool = True
    substrates: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    pathway_ids: list[str] = field(default_factory=list)


def parse_kegg_reaction(text: str) -> KEGGReactionData | None:
    """Parse KEGG flat-file format reaction entry.

    Example format:
        ENTRY       R00200                      Reaction
        NAME        ATP:D-glucose 6-phosphotransferase
        DEFINITION  ATP + D-Glucose <=> ADP + D-Glucose 6-phosphate
        EQUATION    C00002 + C00031 <=> C00008 + C00092
        ENZYME      2.7.1.1  2.7.1.2
        PATHWAY     rn00010  Glycolysis / Gluconeogenesis
    """
    if not text or not isinstance(text, str):
        return None

    data = KEGGReactionData()
    current_field = ""
    current_value: list[str] = []

    def _commit_field() -> None:
        nonlocal current_field, current_value
        if not current_field:
            return
        value = " ".join(current_value).strip()
        if current_field == "ENTRY":
            # "R00200                      Reaction"
            match = re.match(r"(\S+)", value)
            if match:
                data.entry_id = match.group(1)
        elif current_field == "NAME":
            data.name = value
        elif current_field == "DEFINITION":
            data.definition = value
        elif current_field == "EQUATION":
            data.equation = value
            _parse_equation(value)
        elif current_field == "ENZYME":
            data.enzyme = value.split()
        elif current_field == "PATHWAY":
            # May span multiple lines
            for line_part in current_value:
                match = re.match(r"(\S+)", line_part.strip())
                if match:
                    data.pathway_ids.append(match.group(1))
        current_field = ""
        current_value = []

    def _parse_equation(eq: str) -> None:
        """Parse KEGG equation into substrates and products."""
        # Determine reversibility
        if "<=>" in eq:
            data.is_reversible = True
            left, right = eq.split("<=>", 1)
        elif "=>" in eq:
            data.is_reversible = False
            left, right = eq.split("=>", 1)
        elif "=" in eq:
            # Fallback: plain '=' treated as reversible
            data.is_reversible = True
            left, right = eq.split("=", 1)
        else:
            return

        data.substrates = _extract_compound_ids(left)
        data.products = _extract_compound_ids(right)

    for line in text.splitlines():
        if line.startswith("///"):
            _commit_field()
            break

        # Check if this is a new field (starts with uppercase letter at column 0)
        if line and not line[0].isspace() and line[0].isupper():
            _commit_field()
            parts = line.split(None, 1)
            current_field = parts[0]
            current_value = [parts[1]] if len(parts) > 1 else []
        elif line.startswith(" ") and current_field:
            # Continuation line
            current_value.append(line.strip())

    _commit_field()

    if not data.entry_id:
        return None
    return data


def _extract_compound_ids(side: str) -> list[str]:
    """Extract KEGG compound IDs (Cxxxxx, Gxxxxx) from one side of an equation."""
    return re.findall(r"\b([CG]\d{5})\b", side)


def compute_match_ratio(model_ids: list[str], kegg_ids: list[str]) -> float:
    """Compute Jaccard similarity between model metabolite IDs and KEGG compound IDs."""
    if not model_ids and not kegg_ids:
        return 1.0  # Both empty = match
    if not model_ids or not kegg_ids:
        return 0.0

    model_set = set(model_ids)
    kegg_set = set(kegg_ids)
    intersection = model_set & kegg_set
    union = model_set | kegg_set

    return len(intersection) / len(union) if union else 0.0


class KEGGClient(BaseAPIClient):
    """Client for the KEGG REST API with 3-stage reaction verification."""

    def __init__(self, organism_code: str = "eco", cache_manager=None) -> None:
        super().__init__(
            name="kegg",
            base_url=KEGG_API_BASE,
            rate=RATE_LIMITS["kegg"],
            cache_manager=cache_manager,
        )
        self.organism_code = organism_code

    async def get_reaction(self, kegg_id: str) -> dict | str | None:
        """Get KEGG reaction entry."""
        return await self.get(
            f"/get/{kegg_id}",
            cache_key=f"kegg:reaction:{kegg_id}",
            cache_ttl=7 * 24 * 3600,
        )

    async def get_reaction_parsed(self, kegg_id: str) -> KEGGReactionData | None:
        """Get and parse a KEGG reaction entry."""
        raw = await self.get_reaction(kegg_id)
        if raw and isinstance(raw, str):
            return parse_kegg_reaction(raw)
        return None

    async def check_evidence(
        self,
        reaction: Reaction,
        ec_numbers: list[str] | None = None,
        kegg_reaction_ids: list[str] | None = None,
        model_substrates_kegg: list[str] | None = None,
        model_products_kegg: list[str] | None = None,
        **kwargs,
    ) -> list[EvidenceItem]:
        """KEGG-based reaction verification.

        Stage 1: Reaction existence — does the KEGG reaction ID exist?
        Stage 2: Substrate/product matching — do metabolites match?
        """
        items: list[EvidenceItem] = []
        kegg_ids = kegg_reaction_ids or []
        ec_nums = ec_numbers or []
        substrates = model_substrates_kegg or []
        products = model_products_kegg or []

        best_result = None  # Track best match across all KEGG IDs

        for kid in kegg_ids:
            result = await self._verify_reaction(kid, substrates, products)
            if result is not None and (
                best_result is None or result["strength_rank"] > best_result["strength_rank"]
            ):
                best_result = result

        # If no match from direct IDs, try EC number lookup
        if best_result is None and ec_nums:
            for ec in ec_nums[:3]:
                ec_rxn_ids = await self._find_reactions_by_ec(ec)
                for kid in ec_rxn_ids[:3]:
                    result = await self._verify_reaction(kid, substrates, products)
                    if result is not None:
                        result["via_ec"] = ec
                        if (
                            best_result is None
                            or result["strength_rank"] > best_result["strength_rank"]
                        ):
                            best_result = result

        if best_result:
            items.append(best_result["evidence_item"])
        else:
            items.append(
                EvidenceItem(
                    source=EvidenceSource.KEGG,
                    strength=EvidenceStrength.ABSENT,
                    description="No KEGG reaction found for this reaction",
                )
            )

        return items

    async def _verify_reaction(
        self,
        kegg_id: str,
        model_substrates: list[str],
        model_products: list[str],
    ) -> dict | None:
        """Verify a single KEGG reaction against model data. Returns result dict or None."""
        parsed = await self.get_reaction_parsed(kegg_id)
        if parsed is None:
            return None

        # Stage 1: Reaction exists
        url = f"https://www.kegg.jp/entry/{kegg_id}"

        # Stage 2: Substrate/product matching
        sub_ratio = compute_match_ratio(model_substrates, parsed.substrates)
        prod_ratio = compute_match_ratio(model_products, parsed.products)
        avg_match = (sub_ratio + prod_ratio) / 2

        # Reject if no metabolite overlap at all — ID mapping is likely wrong
        if avg_match < 0.2:
            return None

        # Determine strength
        if avg_match >= 0.8:
            strength = EvidenceStrength.STRONG
            rank = 3
        elif avg_match >= 0.5:
            strength = EvidenceStrength.MODERATE
            rank = 2
        else:
            strength = EvidenceStrength.WEAK
            rank = 1

        # Compute overlap counts for description
        model_sub_set = set(model_substrates)
        kegg_sub_set = set(parsed.substrates)
        sub_overlap = len(model_sub_set & kegg_sub_set)
        sub_total = len(model_sub_set | kegg_sub_set)

        model_prod_set = set(model_products)
        kegg_prod_set = set(parsed.products)
        prod_overlap = len(model_prod_set & kegg_prod_set)
        prod_total = len(model_prod_set | kegg_prod_set)

        # Build description
        desc_parts = [
            f"KEGG reaction {kegg_id}",
        ]
        if parsed.name:
            desc_parts.append(f"({parsed.name})")
        desc_parts.append(
            f"\u2014 substrates: {sub_overlap}/{sub_total} matched ({sub_ratio:.0%}), "
            f"products: {prod_overlap}/{prod_total} matched ({prod_ratio:.0%})"
        )
        if parsed.enzyme:
            desc_parts.append(f" | EC: {', '.join(parsed.enzyme[:3])}")

        description = " ".join(desc_parts)

        return {
            "evidence_item": EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=strength,
                description=description,
                url=url,
                raw_data={
                    "kegg_id": kegg_id,
                    "substrate_match": sub_ratio,
                    "product_match": prod_ratio,
                    "model_substrates": model_substrates,
                    "model_products": model_products,
                    "kegg_substrates": parsed.substrates,
                    "kegg_products": parsed.products,
                    "enzyme": parsed.enzyme,
                    "pathway_ids": parsed.pathway_ids,
                    "kegg_parsed": parsed,
                },
            ),
            "strength_rank": rank,
            "substrate_match": sub_ratio,
            "product_match": prod_ratio,
        }

    async def _find_reactions_by_ec(self, ec_number: str) -> list[str]:
        """Find KEGG reaction IDs linked to an EC number."""
        data = await self.get(
            f"/link/reaction/ec:{ec_number}",
            cache_key=f"kegg:ec2rxn:{ec_number}",
            cache_ttl=30 * 24 * 3600,
        )
        if not data or not isinstance(data, str):
            return []
        # Parse "ec:X.X.X.X\trn:RXXXXX" lines
        ids = re.findall(r"rn:(R\d{5})", data)
        return ids
