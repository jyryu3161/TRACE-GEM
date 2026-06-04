"""Evidence type definitions, strength classifiers, and source registry."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.models import EvidenceSource, EvidenceStrength

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
}

# Default color coding for evidence strength (hex literals — no GUI dependency)
STRENGTH_COLORS: dict[EvidenceStrength, str] = {
    EvidenceStrength.STRONG: "#2ecc71",
    EvidenceStrength.MODERATE: "#f1c40f",
    EvidenceStrength.WEAK: "#e67e22",
    EvidenceStrength.ABSENT: "#e74c3c",
}

# Default source colors (hex literals)
_DEFAULT_SOURCE_COLORS: dict[EvidenceSource, str] = {
    EvidenceSource.KEGG: "#3498db",
    EvidenceSource.BIGG: "#2ecc71",
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
        color=_DEFAULT_SOURCE_COLORS[EvidenceSource.KEGG],
        requires_api_key=False,
        config_key="",
        enable_key="",
        weight_key="weight_kegg",
        description="KEGG pathway database verification",
        order=0,
    ),
    EvidenceSource.BIGG: SourceConfig(
        display_name="BiGG Models",
        color=_DEFAULT_SOURCE_COLORS[EvidenceSource.BIGG],
        requires_api_key=False,
        config_key="",
        enable_key="enable_bigg",
        weight_key="weight_bigg",
        description="BiGG universal reaction database",
        order=1,
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
        if (sc.enable_key and getattr(config, sc.enable_key, False)) or not sc.enable_key:
            active.append(source)
    return active
