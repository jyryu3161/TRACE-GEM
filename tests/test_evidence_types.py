"""Tests for the (KEGG-only) evidence source registry and helpers."""

from __future__ import annotations

from src.core.models import EvidenceSource
from src.evidence.evidence_types import (
    SOURCE_REGISTRY,
    SourceConfig,
    get_active_sources,
    get_ordered_sources,
    get_source_config,
)


class TestSourceRegistry:
    def test_only_kegg_registered(self) -> None:
        # Evidence is KEGG-only; BiGG is not an evidence source.
        assert len(SOURCE_REGISTRY) == 1
        assert EvidenceSource.KEGG in SOURCE_REGISTRY
        assert EvidenceSource.BIGG not in SOURCE_REGISTRY

    def test_source_config_fields(self) -> None:
        cfg = SOURCE_REGISTRY[EvidenceSource.KEGG]
        assert cfg.display_name == "KEGG"
        assert cfg.order == 0
        assert cfg.requires_api_key is False

    def test_no_sources_require_api_key(self) -> None:
        assert all(not cfg.requires_api_key for cfg in SOURCE_REGISTRY.values())
        assert all(not cfg.config_key for cfg in SOURCE_REGISTRY.values())


class TestGetSourceConfig:
    def test_returns_config(self) -> None:
        cfg = get_source_config(EvidenceSource.KEGG)
        assert isinstance(cfg, SourceConfig)
        assert cfg.display_name == "KEGG"


class TestGetOrderedSources:
    def test_returns_only_kegg(self) -> None:
        ordered = get_ordered_sources()
        assert len(ordered) == 1
        assert ordered[0][0] == EvidenceSource.KEGG


class TestGetActiveSources:
    def test_only_kegg_active(self) -> None:
        active = get_active_sources(object())
        assert active == [EvidenceSource.KEGG]
