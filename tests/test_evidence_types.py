"""Tests for evidence source registry and helpers."""

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
    def test_all_sources_registered(self) -> None:
        assert len(SOURCE_REGISTRY) == 2
        for source in EvidenceSource:
            assert source in SOURCE_REGISTRY

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
        cfg = get_source_config(EvidenceSource.BIGG)
        assert isinstance(cfg, SourceConfig)
        assert cfg.display_name == "BiGG Models"


class TestGetOrderedSources:
    def test_returns_sorted_by_order(self) -> None:
        ordered = get_ordered_sources()
        assert len(ordered) == 2
        orders = [sc.order for _, sc in ordered]
        assert orders == sorted(orders)

    def test_kegg_first(self) -> None:
        ordered = get_ordered_sources()
        assert ordered[0][0] == EvidenceSource.KEGG


class TestGetActiveSources:
    def test_all_enabled(self) -> None:
        class MockConfig:
            enable_bigg = True

        active = get_active_sources(MockConfig())
        assert active == [EvidenceSource.KEGG, EvidenceSource.BIGG]

    def test_only_kegg_when_bigg_disabled(self) -> None:
        class MockConfig:
            enable_bigg = False

        active = get_active_sources(MockConfig())
        assert active == [EvidenceSource.KEGG]
