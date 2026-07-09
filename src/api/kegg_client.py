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

# KEGG compounds that commonly act as reaction currency/cofactors. These can
# dominate Jaccard matching while adding little evidence about reaction identity.
_CURRENCY_COMPOUND_IDS = {
    "C00001",  # H2O
    "C00002",  # ATP
    "C00003",  # NAD+
    "C00004",  # NADH
    "C00005",  # NADPH
    "C00006",  # NADP+
    "C00007",  # O2
    "C00008",  # ADP
    "C00009",  # phosphate
    "C00010",  # CoA
    "C00011",  # CO2
    "C00013",  # diphosphate
    "C00014",  # ammonia
    "C00015",  # UDP
    "C00016",  # FAD
    "C00019",  # S-adenosyl-L-methionine
    "C00020",  # AMP
    "C00035",  # GDP
    "C00044",  # GTP
    "C00075",  # UTP
    "C00080",  # H+
}


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
    """Compute Jaccard similarity between model metabolite IDs and KEGG compound IDs.

    An empty-vs-empty comparison is treated as *no evidence* (0.0), not a
    perfect match: if neither the model reaction nor the KEGG entry contributed
    any compound IDs for a side, there is nothing to corroborate. Returning 1.0
    here would let a reaction with zero metabolite evidence be scored STRONG/High.
    """
    if not model_ids or not kegg_ids:
        return 0.0

    model_set = set(model_ids)
    kegg_set = set(kegg_ids)
    intersection = model_set & kegg_set
    union = model_set | kegg_set

    return len(intersection) / len(union) if union else 0.0


def _filter_currency(ids: list[str]) -> list[str]:
    """Return KEGG compound IDs excluding common currency metabolites."""
    return [cid for cid in ids if cid not in _CURRENCY_COMPOUND_IDS]


def compute_informative_match(
    model_ids: list[str],
    kegg_ids: list[str],
) -> tuple[float, list[str], list[str], bool]:
    """Compute match ratio after removing currency metabolites when possible.

    Returns:
        ``(ratio, filtered_model_ids, filtered_kegg_ids, used_filter)``.
        If filtering would leave one side empty, falls back to the original
        lists so currency-only reactions can still be evaluated.
    """
    filtered_model = _filter_currency(model_ids)
    filtered_kegg = _filter_currency(kegg_ids)
    if filtered_model and filtered_kegg:
        return (
            compute_match_ratio(filtered_model, filtered_kegg),
            filtered_model,
            filtered_kegg,
            True,
        )
    return compute_match_ratio(model_ids, kegg_ids), model_ids, kegg_ids, False


# --- Rule-based reconciliation / EC-concordance states -----------------------
# Tiers are decided from these categorical states (not tuned float cutoffs).
RECON_FULL = "full"
RECON_PARTIAL = "partial"
RECON_CONTRADICTORY = "none_contradictory"
RECON_UNVERIFIABLE = "unverifiable"
_RECON_RANK = {RECON_FULL: 3, RECON_PARTIAL: 2, RECON_UNVERIFIABLE: 1, RECON_CONTRADICTORY: 0}

EC_CONCORDANT = "concordant"
EC_DISCORDANT = "discordant"
EC_UNKNOWN = "unknown"
_EC_RANK = {EC_CONCORDANT: 2, EC_UNKNOWN: 1, EC_DISCORDANT: 0}


def _reconcile_side(model_inf: set[str], kegg_inf: set[str]) -> str:
    """Reconcile one side (substrates or products) of informative compounds.

    Empty on either side ⇒ UNVERIFIABLE (no currency-only fallback). FULL
    requires symmetric set equality — strictly more conservative than a
    high-Jaccard threshold.
    """
    if not model_inf or not kegg_inf:
        return RECON_UNVERIFIABLE
    matched = model_inf & kegg_inf
    if matched == model_inf == kegg_inf:
        return RECON_FULL
    if matched:
        return RECON_PARTIAL
    return RECON_CONTRADICTORY


def _aggregate_reconciliation(sub_state: str, prod_state: str) -> str:
    states = {sub_state, prod_state}
    if RECON_CONTRADICTORY in states:
        return RECON_CONTRADICTORY
    if states == {RECON_UNVERIFIABLE}:
        return RECON_UNVERIFIABLE
    if states == {RECON_FULL}:
        return RECON_FULL
    # One FULL side with the other UNVERIFIABLE, or any PARTIAL ⇒ PARTIAL
    # (conservative: the whole reaction was not verified).
    return RECON_PARTIAL


def reconciliation_state(
    model_substrates: list[str],
    model_products: list[str],
    kegg_substrates: list[str],
    kegg_products: list[str],
) -> tuple[str, dict]:
    """Best-of-both-orientation metabolite reconciliation state + detail.

    KEGG's substrate/product split is direction-arbitrary, so both orientations
    are scored and the stronger (non-contradictory) reading is kept.
    """
    m_sub, m_prod = set(_filter_currency(model_substrates)), set(_filter_currency(model_products))
    k_sub, k_prod = set(_filter_currency(kegg_substrates)), set(_filter_currency(kegg_products))

    orientations = [
        ("forward", (m_sub, k_sub), (m_prod, k_prod)),
        ("reverse", (m_sub, k_prod), (m_prod, k_sub)),
    ]
    best: tuple[str, str, tuple, tuple] | None = None
    for name, (ms1, ks1), (ms2, ks2) in orientations:
        agg = _aggregate_reconciliation(_reconcile_side(ms1, ks1), _reconcile_side(ms2, ks2))
        if best is None or _RECON_RANK[agg] > _RECON_RANK[best[0]]:
            best = (agg, name, (ms1, ks1), (ms2, ks2))
    agg, name, (ms1, ks1), (ms2, ks2) = best  # type: ignore[misc]
    info = {
        "orientation": name,
        "sub_matched": len(ms1 & ks1),
        "sub_total": len(ms1 | ks1),
        "prod_matched": len(ms2 & ks2),
        "prod_total": len(ms2 | ks2),
    }
    return agg, info


def ec_concordance_state(model_ec: list[str], kegg_ec: list[str]) -> str:
    """Compare model EC numbers with the KEGG entry's EC numbers.

    Exact 4-level overlap ⇒ CONCORDANT; sharing only the 3-level subclass ⇒
    UNKNOWN (ambiguous); disjoint at the 3-level class ⇒ DISCORDANT; missing on
    either side ⇒ UNKNOWN.
    """
    model = {e.strip() for e in model_ec if e and e.strip()}
    kegg = {e.strip() for e in kegg_ec if e and e.strip()}
    if not model or not kegg:
        return EC_UNKNOWN
    if model & kegg:
        return EC_CONCORDANT
    prefix3 = lambda ec: ".".join(ec.split(".")[:3])  # noqa: E731
    if {prefix3(e) for e in model} & {prefix3(e) for e in kegg}:
        return EC_UNKNOWN
    return EC_DISCORDANT


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
            result = await self._verify_reaction(kid, substrates, products, ec_nums)
            if self._is_better_kegg_result(result, best_result):
                best_result = result

        # If no anchor yet, or the best anchor contradicts the model, try to
        # find a KEGG reaction via the model's EC numbers.
        if (best_result is None or not best_result["verified"]) and ec_nums:
            for ec in ec_nums[:3]:
                ec_rxn_ids = await self._find_reactions_by_ec(ec)
                for kid in ec_rxn_ids[:3]:
                    result = await self._verify_reaction(kid, substrates, products, ec_nums)
                    if result is not None:
                        result["via_ec"] = ec
                        if self._is_better_kegg_result(result, best_result):
                            best_result = result

        if best_result:
            items.append(best_result["evidence_item"])
        else:
            # No KEGG entry could be retrieved by any route \u21d2 not KEGG-anchored.
            items.append(
                EvidenceItem(
                    source=EvidenceSource.KEGG,
                    strength=EvidenceStrength.ABSENT,
                    description="No KEGG reaction found for this reaction",
                    raw_data={
                        "kegg_anchored": False,
                        "reconciliation_state": RECON_UNVERIFIABLE,
                        "ec_concordance_state": EC_UNKNOWN,
                    },
                )
            )

        return items

    @staticmethod
    def _is_better_kegg_result(result: dict | None, current: dict | None) -> bool:
        """Rank KEGG verifications by (reconciliation state, EC concordance)."""
        if result is None:
            return False
        if current is None:
            return True
        r = (_RECON_RANK[result["reconciliation_state"]], _EC_RANK[result["ec_concordance_state"]])
        c = (_RECON_RANK[current["reconciliation_state"]], _EC_RANK[current["ec_concordance_state"]])
        return r > c

    # Legacy per-item strength (drives the display-only kegg_score, NOT the tier).
    _RECON_STRENGTH = {
        RECON_FULL: EvidenceStrength.STRONG,
        RECON_PARTIAL: EvidenceStrength.MODERATE,
        RECON_UNVERIFIABLE: EvidenceStrength.WEAK,
        RECON_CONTRADICTORY: EvidenceStrength.ABSENT,
    }

    async def _verify_reaction(
        self,
        kegg_id: str,
        model_substrates: list[str],
        model_products: list[str],
        model_ec: list[str] | None = None,
    ) -> dict | None:
        """Verify a single KEGG reaction against model data. Returns result dict or None.

        Computes the categorical metabolite-reconciliation and EC-concordance
        states that the scorer turns into a tier. Returns ``None`` only when the
        KEGG entry itself cannot be retrieved (not KEGG-anchored via this ID).
        """
        parsed = await self.get_reaction_parsed(kegg_id)
        if parsed is None:
            return None

        url = f"https://www.kegg.jp/entry/{kegg_id}"
        recon, info = reconciliation_state(
            model_substrates, model_products, parsed.substrates, parsed.products
        )
        ec_state = ec_concordance_state(model_ec or [], parsed.enzyme)
        strength = self._RECON_STRENGTH[recon]
        verified = recon != RECON_CONTRADICTORY

        sub_ratio = info["sub_matched"] / info["sub_total"] if info["sub_total"] else 0.0
        prod_ratio = info["prod_matched"] / info["prod_total"] if info["prod_total"] else 0.0

        desc_parts = [f"KEGG reaction {kegg_id}"]
        if parsed.name:
            desc_parts.append(f"({parsed.name})")
        desc_parts.append(
            f"\u2014 metabolites: {recon.replace('_', ' ')}"
            f" (substrates {info['sub_matched']}/{info['sub_total']},"
            f" products {info['prod_matched']}/{info['prod_total']})"
        )
        desc_parts.append(f"| EC: {ec_state}")
        if parsed.enzyme:
            desc_parts.append(f"({', '.join(parsed.enzyme[:3])})")
        description = " ".join(desc_parts)

        return {
            "evidence_item": EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=strength,
                description=description,
                url=url,
                raw_data={
                    "kegg_id": kegg_id,
                    "kegg_anchored": True,
                    "reconciliation_state": recon,
                    "ec_concordance_state": ec_state,
                    "reconciliation_detail": info,
                    "substrate_match": sub_ratio,
                    "product_match": prod_ratio,
                    "raw_model_substrates": model_substrates,
                    "raw_model_products": model_products,
                    "raw_kegg_substrates": parsed.substrates,
                    "raw_kegg_products": parsed.products,
                    "model_ec": list(model_ec or []),
                    "kegg_enzyme": parsed.enzyme,
                    "pathway_ids": parsed.pathway_ids,
                    "kegg_parsed": parsed,
                },
            ),
            "kegg_anchored": True,
            "reconciliation_state": recon,
            "ec_concordance_state": ec_state,
            "verified": verified,
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
