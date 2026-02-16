"""Evidence type definitions, strength classifiers, and source registry."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.models import EvidenceSource, EvidenceStrength
from src.gui.theme import THEME

# Display labels
STRENGTH_LABELS = {
    EvidenceStrength.STRONG: "Strong",
    EvidenceStrength.MODERATE: "Moderate",
    EvidenceStrength.WEAK: "Weak",
    EvidenceStrength.ABSENT: "Not found",
}

SOURCE_LABELS = {
    EvidenceSource.KEGG: "KEGG",
    EvidenceSource.BIGG: "BiGG Models",
    EvidenceSource.UNIPROT: "UniProt",
    EvidenceSource.PUBMED: "PubMed",
    EvidenceSource.METACYC: "MetaCyc",
    EvidenceSource.GEMINI: "Gemini",
    EvidenceSource.PERPLEXITY: "Perplexity",
}

# Color coding for evidence strength (hex)
STRENGTH_COLORS = {
    EvidenceStrength.STRONG: THEME.strength_strong,
    EvidenceStrength.MODERATE: THEME.strength_moderate,
    EvidenceStrength.WEAK: THEME.strength_weak,
    EvidenceStrength.ABSENT: THEME.strength_absent,
}


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for a single evidence source."""

    display_name: str
    color: str
    requires_api_key: bool
    config_key: str  # Attribute name on Config for API key (empty if none)
    enable_key: str  # Attribute name on Config for enable flag
    weight_key: str  # Attribute name on Config for weight
    description: str
    order: int  # Display order


SOURCE_REGISTRY: dict[EvidenceSource, SourceConfig] = {
    EvidenceSource.KEGG: SourceConfig(
        display_name="KEGG",
        color=THEME.source_kegg,
        requires_api_key=False,
        config_key="",
        enable_key="",
        weight_key="weight_kegg",
        description="KEGG pathway database verification",
        order=0,
    ),
    EvidenceSource.BIGG: SourceConfig(
        display_name="BiGG Models",
        color=THEME.source_bigg,
        requires_api_key=False,
        config_key="",
        enable_key="enable_bigg",
        weight_key="weight_bigg",
        description="BiGG universal reaction database",
        order=1,
    ),
    EvidenceSource.UNIPROT: SourceConfig(
        display_name="UniProt",
        color=THEME.source_uniprot,
        requires_api_key=False,
        config_key="",
        enable_key="enable_uniprot",
        weight_key="weight_uniprot",
        description="UniProt protein/gene evidence",
        order=2,
    ),
    EvidenceSource.METACYC: SourceConfig(
        display_name="MetaCyc",
        color=THEME.source_metacyc,
        requires_api_key=False,
        config_key="",
        enable_key="enable_metacyc",
        weight_key="weight_metacyc",
        description="MetaCyc/BioCyc pathway database",
        order=3,
    ),
    EvidenceSource.PUBMED: SourceConfig(
        display_name="PubMed",
        color=THEME.source_pubmed,
        requires_api_key=False,
        config_key="pubmed_api_key",
        enable_key="enable_pubmed",
        weight_key="weight_pubmed",
        description="PubMed literature evidence",
        order=4,
    ),
    EvidenceSource.GEMINI: SourceConfig(
        display_name="Gemini",
        color=THEME.source_gemini,
        requires_api_key=True,
        config_key="gemini_api_key",
        enable_key="enable_gemini",
        weight_key="weight_gemini",
        description="Gemini LLM reaction verification",
        order=5,
    ),
    EvidenceSource.PERPLEXITY: SourceConfig(
        display_name="Perplexity",
        color=THEME.source_perplexity,
        requires_api_key=True,
        config_key="perplexity_api_key",
        enable_key="enable_perplexity",
        weight_key="weight_perplexity",
        description="Perplexity species-specific verification",
        order=6,
    ),
}


def get_source_config(source: EvidenceSource) -> SourceConfig:
    """Get configuration for a source."""
    return SOURCE_REGISTRY[source]


def get_ordered_sources() -> list[tuple[EvidenceSource, SourceConfig]]:
    """Get all sources sorted by display order."""
    return sorted(SOURCE_REGISTRY.items(), key=lambda x: x[1].order)


def get_active_sources(config: object) -> list[EvidenceSource]:
    """Get list of enabled sources based on config flags."""
    active = []
    for source, sc in get_ordered_sources():
        if source == EvidenceSource.KEGG:
            active.append(source)  # KEGG is always active
            continue
        if sc.enable_key and getattr(config, sc.enable_key, False) or not sc.enable_key:
            active.append(source)
    return active
