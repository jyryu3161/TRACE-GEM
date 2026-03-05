"""Tests for evidence_types module — SOURCE_REGISTRY, helpers."""

from __future__ import annotations

import pytest

from src.core.models import EvidenceSource

try:
    from src.evidence.evidence_types import (
        SOURCE_REGISTRY,
        SourceConfig,
        get_active_sources,
        get_ordered_sources,
        get_source_config,
    )

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

pytestmark = pytest.mark.skipif(not HAS_DEPS, reason="PySide6 not available")


class TestSourceRegistry:
    def test_all_six_sources_registered(self) -> None:
        assert len(SOURCE_REGISTRY) == 6
        for source in EvidenceSource:
            assert source in SOURCE_REGISTRY

    def test_source_config_fields(self) -> None:
        cfg = SOURCE_REGISTRY[EvidenceSource.KEGG]
        assert cfg.display_name == "KEGG"
        assert cfg.order == 0
        assert cfg.requires_api_key is False

    def test_gemini_requires_api_key(self) -> None:
        cfg = SOURCE_REGISTRY[EvidenceSource.GEMINI]
        assert cfg.requires_api_key is True
        assert cfg.config_key == "gemini_api_key"


class TestGetSourceConfig:
    def test_returns_config(self) -> None:
        cfg = get_source_config(EvidenceSource.BIGG)
        assert isinstance(cfg, SourceConfig)
        assert cfg.display_name == "BiGG Models"


class TestGetOrderedSources:
    def test_returns_sorted_by_order(self) -> None:
        ordered = get_ordered_sources()
        assert len(ordered) == 6
        orders = [sc.order for _, sc in ordered]
        assert orders == sorted(orders)

    def test_kegg_first(self) -> None:
        ordered = get_ordered_sources()
        assert ordered[0][0] == EvidenceSource.KEGG


class TestGetActiveSources:
    def test_all_enabled(self) -> None:
        """Mock config with all sources enabled."""

        class MockConfig:
            enable_bigg = True
            enable_uniprot = True
            enable_pubmed = True
            enable_gemini = True
            enable_perplexity = True

        active = get_active_sources(MockConfig())
        assert len(active) == 6

    def test_only_kegg_when_all_disabled(self) -> None:
        class MockConfig:
            enable_bigg = False
            enable_uniprot = False
            enable_pubmed = False
            enable_gemini = False
            enable_perplexity = False

        active = get_active_sources(MockConfig())
        assert active == [EvidenceSource.KEGG]

    def test_partial_enable(self) -> None:
        class MockConfig:
            enable_bigg = True
            enable_uniprot = False
            enable_pubmed = True
            enable_gemini = False
            enable_perplexity = True

        active = get_active_sources(MockConfig())
        assert EvidenceSource.KEGG in active
        assert EvidenceSource.BIGG in active
        assert EvidenceSource.PUBMED in active
        assert EvidenceSource.PERPLEXITY in active
        assert EvidenceSource.UNIPROT not in active
        assert EvidenceSource.GEMINI not in active
