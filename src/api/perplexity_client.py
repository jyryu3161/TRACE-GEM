"""Perplexity Sonar client for species-specific reaction existence verification."""

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

logger = logging.getLogger("gem_evaluator.api.perplexity")

_EXISTENCE_PROMPT = """\
You are a biochemistry expert. Determine whether the following metabolic \
reaction is known to occur in {organism}.

Reaction: {reaction_name}
Equation: {equation}
EC Number(s): {ec_numbers}
Subsystem/Pathway: {subsystem}
Associated genes: {genes}

Metabolites involved:
- Reactants: {reactant_names}
- Products: {product_names}

Search for evidence that this specific biochemical reaction occurs in \
{organism}. Consider:
1. Is this enzyme/reaction documented in {organism} metabolic pathways \
(KEGG, MetaCyc, BRENDA)?
2. Are the associated genes known to encode enzymes catalyzing this \
reaction in {organism}?
3. Is there experimental evidence from published literature?
4. Is this reaction part of core metabolism or a species-specific pathway?
5. Are the listed reactants and products known metabolites present in {organism}?
6. Are there any metabolites that are unusual or not typically found in {organism}?

Respond ONLY with a valid JSON object (no markdown):
{{"exists_in_organism": true or false or null, "confidence": 0.0 to 1.0, \
"evidence_summary": "brief summary", "sources": ["source1", "source2"], \
"metabolites_verified": true or false or null, \
"unusual_metabolites": ["metabolite name if any"]}}"""


class PerplexityClient:
    """Perplexity Sonar-based species-specific reaction existence verification."""

    def __init__(self, api_key: str, cache_manager=None) -> None:
        from openai import AsyncOpenAI  # type: ignore[import-untyped]

        self._client = AsyncOpenAI(
            api_key=api_key.strip(),
            base_url="https://api.perplexity.ai",
        )
        self._cache = cache_manager
        self._rate_limiter = RateLimiter(rate=2.0, burst=2)

    async def verify_reaction_existence(
        self,
        reaction: Reaction,
        organism: str,
        ec_numbers: list[str],
        reactant_names: dict[str, str] | None = None,
        product_names: dict[str, str] | None = None,
    ) -> EvidenceItem:
        """Verify whether a reaction exists in the given organism using web search."""
        cache_key = f"perplexity:existence:v2:{reaction.id}:{organism}"

        # Check cache
        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None and isinstance(cached, dict):
                return self._parse_response(cached, organism)

        # Build metabolite name strings
        r_names = reactant_names or {}
        p_names = product_names or {}
        reactant_str = ", ".join(f"{v} ({k})" for k, v in r_names.items()) or "N/A"
        product_str = ", ".join(f"{v} ({k})" for k, v in p_names.items()) or "N/A"

        # Build prompt
        prompt = _EXISTENCE_PROMPT.format(
            organism=organism,
            reaction_name=reaction.name,
            equation=reaction.equation,
            ec_numbers=", ".join(ec_numbers) or "N/A",
            subsystem=reaction.subsystem or "N/A",
            genes=", ".join(reaction.genes) or "N/A",
            reactant_names=reactant_str,
            product_names=product_str,
        )

        # Rate limit and call API
        await self._rate_limiter.acquire()

        try:
            response = await self._client.chat.completions.create(
                model="sonar",
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            parsed = self._extract_json(text)

            # Cache result
            if parsed and self._cache:
                await self._cache.set(cache_key, parsed, ttl=7 * 24 * 3600)

            if parsed:
                return self._parse_response(parsed, organism)

            # Fallback
            return self._fallback_parse(text, organism)

        except Exception as e:
            logger.warning("Perplexity API error for %s: %s", reaction.id, e)
            return EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.WEAK,
                description=f"Species verification error: {e}",
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

    def _parse_response(self, data: dict, organism: str) -> EvidenceItem:
        """Parse structured response into EvidenceItem."""
        exists = data.get("exists_in_organism")
        confidence = float(data.get("confidence", 0.0))
        summary = data.get("evidence_summary", "No summary provided")
        sources = data.get("sources", [])
        metabolites_verified = data.get("metabolites_verified")
        unusual_metabolites = data.get("unusual_metabolites", [])

        # Apply 0.7x penalty if metabolites not verified
        if metabolites_verified is False:
            confidence *= 0.7

        if exists is True and confidence >= 0.7:
            strength = EvidenceStrength.STRONG
        elif exists is True and confidence >= 0.4:
            strength = EvidenceStrength.MODERATE
        else:
            strength = EvidenceStrength.WEAK

        if exists is True:
            status_text = "Found"
        elif exists is False:
            status_text = "Not found"
        else:
            status_text = "Uncertain"

        met_tag = "(metabolites: verified)" if metabolites_verified is True else (
            "(metabolites: issues found)" if metabolites_verified is False else ""
        )
        description = (
            f"Species Check ({organism}): {status_text} (confidence: {confidence:.0%}) — {summary}"
        )
        if met_tag:
            description += f" {met_tag}"

        return EvidenceItem(
            source=EvidenceSource.PERPLEXITY,
            strength=strength,
            description=description,
            raw_data={
                "exists_in_organism": exists,
                "confidence": confidence,
                "evidence_summary": summary,
                "sources": sources,
                "metabolites_verified": metabolites_verified,
                "unusual_metabolites": unusual_metabolites,
            },
        )

    def _fallback_parse(self, text: str, organism: str) -> EvidenceItem:
        """Fallback parsing when JSON extraction fails."""
        text_lower = text.lower()
        if "yes" in text_lower or "exists" in text_lower:
            return EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.MODERATE,
                description=f"Species Check ({organism}): Likely exists (fallback parse)",
                raw_data={"raw_text": text[:500], "fallback": True},
            )
        return EvidenceItem(
            source=EvidenceSource.PERPLEXITY,
            strength=EvidenceStrength.WEAK,
            description=f"Species Check ({organism}): Could not determine existence",
            raw_data={"raw_text": text[:500], "fallback": True},
        )

    async def close(self) -> None:
        """Close the async HTTP client."""
        await self._client.close()
