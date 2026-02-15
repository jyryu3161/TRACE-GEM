"""Gemini 2.5 Flash client for KEGG match verification."""

from __future__ import annotations

import json
import logging
import re

from src.api.rate_limiter import RateLimiter
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)

logger = logging.getLogger("gem_evaluator.api.gemini")

_VERIFY_PROMPT = """\
You are an expert biochemist specializing in genome-scale metabolic models \
and KEGG database curation.

A metabolic model for {organism} contains this reaction:
- Model ID: {reaction_id}
- Name: {reaction_name}
- Equation: {equation}
- EC Numbers: {ec_numbers}
- Subsystem: {subsystem}

This was mapped to KEGG reaction {kegg_id}:
- KEGG Name: {kegg_name}
- KEGG Definition: {kegg_definition}
- KEGG Equation (compound IDs): {kegg_equation}
- KEGG Enzymes: {kegg_enzymes}

Automated matching results:
- Substrate match: {sub_ratio:.0%} (model: {model_substrates} → KEGG: {kegg_substrates})
- Product match: {prod_ratio:.0%} (model: {model_products} → KEGG: {kegg_products})

Metabolites in this reaction (model names):
- Reactants: {reactant_names}
- Products: {product_names}

Evaluate whether this KEGG reaction correctly represents the model reaction:
1. Are these biochemically identical reactions despite naming/ID differences?
2. Could mismatches be due to compartment variants \
(cytoplasmic vs mitochondrial vs periplasmic)?
3. Are missing/extra metabolites common cofactors \
(H₂O, H⁺, NAD⁺/NADH, ATP/ADP, CoA) that are often implicit in models?
4. Does EC number alignment support this mapping?
5. Are ALL listed reactants and products known metabolites in {organism}?
6. Are any metabolites unusual or not typically found in {organism} metabolism?

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{{"is_correct_match": true or false, "confidence": 0.0 to 1.0, \
"reasoning": "one sentence", \
"metabolites_in_organism": true or false or null, \
"metabolite_notes": "brief note on any unusual metabolites"}}"""


class GeminiClient:
    """Gemini 2.5 Flash-based reaction match verification."""

    def __init__(self, api_key: str, cache_manager=None) -> None:
        from google import genai  # type: ignore[import-untyped]

        self._client = genai.Client(api_key=api_key.strip())
        self._cache = cache_manager
        self._rate_limiter = RateLimiter(rate=5.0, burst=5)

    async def verify_reaction_match(
        self,
        reaction: Reaction,
        kegg_data: object,
        substrate_match: float,
        product_match: float,
        organism: str,
        reactant_names: dict[str, str] | None = None,
        product_names: dict[str, str] | None = None,
    ) -> EvidenceItem:
        """Verify whether a KEGG mapping is correct using Gemini."""
        from src.api.kegg_client import KEGGReactionData

        if not isinstance(kegg_data, KEGGReactionData):
            return EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.WEAK,
                description="Gemini verification skipped — no KEGG data available",
            )

        cache_key = f"gemini:verify:v2:{reaction.id}:{kegg_data.entry_id}"

        # Check cache
        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None and isinstance(cached, dict):
                return self._parse_response(cached, kegg_data.entry_id)

        # Build metabolite name strings
        r_names = reactant_names or {}
        p_names = product_names or {}
        reactant_str = ", ".join(f"{v} ({k})" for k, v in r_names.items()) or "N/A"
        product_str = ", ".join(f"{v} ({k})" for k, v in p_names.items()) or "N/A"

        # Build prompt
        prompt = _VERIFY_PROMPT.format(
            organism=organism,
            reaction_id=reaction.id,
            reaction_name=reaction.name,
            equation=reaction.equation,
            ec_numbers=", ".join(reaction.annotation.get("ec-code", [])) or "N/A",
            subsystem=reaction.subsystem or "N/A",
            kegg_id=kegg_data.entry_id,
            kegg_name=kegg_data.name or "N/A",
            kegg_definition=kegg_data.definition or "N/A",
            kegg_equation=kegg_data.equation or "N/A",
            kegg_enzymes=", ".join(kegg_data.enzyme) or "N/A",
            sub_ratio=substrate_match,
            prod_ratio=product_match,
            model_substrates=list(reaction.reactants.keys()),
            model_products=list(reaction.products.keys()),
            kegg_substrates=kegg_data.substrates,
            kegg_products=kegg_data.products,
            reactant_names=reactant_str,
            product_names=product_str,
        )

        # Rate limit and call API
        await self._rate_limiter.acquire()

        try:
            response = self._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text or ""
            parsed = self._extract_json(text)

            # Cache result
            if parsed and self._cache:
                await self._cache.set(cache_key, parsed, ttl=30 * 24 * 3600)

            if parsed:
                return self._parse_response(parsed, kegg_data.entry_id)

            # Fallback: try to find true/false in text
            return self._fallback_parse(text, kegg_data.entry_id)

        except Exception as e:
            logger.warning("Gemini API error for %s: %s", reaction.id, e)
            return EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.WEAK,
                description=f"Gemini verification error: {e}",
                raw_data={"error": str(e)},
            )

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON object from response text."""
        # Try direct parse
        try:
            result = json.loads(text.strip())
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            pass

        # Try to find JSON in markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                return result if isinstance(result, dict) else None
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                return result if isinstance(result, dict) else None
            except json.JSONDecodeError:
                pass

        return None

    def _parse_response(self, data: dict, kegg_id: str) -> EvidenceItem:
        """Parse structured response into EvidenceItem."""
        is_match = data.get("is_correct_match", False)
        confidence = float(data.get("confidence", 0.0))
        reasoning = data.get("reasoning", "No reasoning provided")
        metabolites_in_org = data.get("metabolites_in_organism")
        metabolite_notes = data.get("metabolite_notes", "")

        # Apply 0.7x penalty if metabolites not in organism
        if metabolites_in_org is False:
            confidence *= 0.7

        if is_match and confidence >= 0.7:
            strength = EvidenceStrength.STRONG
        elif is_match and confidence >= 0.4:
            strength = EvidenceStrength.MODERATE
        else:
            strength = EvidenceStrength.WEAK

        match_text = "Match" if is_match else "Mismatch"
        met_tag = "(metabolites: verified)" if metabolites_in_org is True else (
            "(metabolites: issues found)" if metabolites_in_org is False else ""
        )
        description = (
            f"LLM Verification ({kegg_id}): {match_text} "
            f"(confidence: {confidence:.0%}) — {reasoning}"
        )
        if met_tag:
            description += f" {met_tag}"

        return EvidenceItem(
            source=EvidenceSource.GEMINI,
            strength=strength,
            description=description,
            raw_data={
                "is_correct_match": is_match,
                "confidence": confidence,
                "reasoning": reasoning,
                "metabolites_in_organism": metabolites_in_org,
                "metabolite_notes": metabolite_notes,
            },
        )

    def _fallback_parse(self, text: str, kegg_id: str) -> EvidenceItem:
        """Fallback parsing when JSON extraction fails."""
        text_lower = text.lower()
        if "true" in text_lower:
            return EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.MODERATE,
                description=f"LLM Verification ({kegg_id}): Likely match (fallback parse)",
                raw_data={"raw_text": text[:500], "fallback": True},
            )
        return EvidenceItem(
            source=EvidenceSource.GEMINI,
            strength=EvidenceStrength.WEAK,
            description=f"LLM Verification ({kegg_id}): Could not determine match",
            raw_data={"raw_text": text[:500], "fallback": True},
        )

    async def close(self) -> None:
        """Cleanup (no persistent connection to close)."""
        pass
