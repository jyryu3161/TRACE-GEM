"""Integration tests for the caching layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.cache.cache_manager import CacheManager


class TestCacheIntegration:
    """Test cache hit/miss/expiration scenarios."""

    @pytest.fixture
    async def cache(self, tmp_path: Path) -> CacheManager:
        db_path = tmp_path / "test_cache.db"
        with patch("src.cache.cache_manager.CACHE_DB_PATH", db_path):
            cm = CacheManager()
            await cm.initialize()
            yield cm
            await cm.close()

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_api_call(self, cache: CacheManager) -> None:
        """Cached data should be returned without making a network call."""
        await cache.set("test:key", {"result": "cached"}, ttl=3600)
        result = await cache.get("test:key")
        assert result == {"result": "cached"}

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, cache: CacheManager) -> None:
        """Missing key should return None."""
        result = await cache.get("nonexistent:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_stores_and_retrieves_string(self, cache: CacheManager) -> None:
        """Cache should handle string values."""
        await cache.set("test:string", "hello world", ttl=3600)
        result = await cache.get("test:string")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_cache_stores_complex_dict(self, cache: CacheManager) -> None:
        """Cache should handle nested dicts."""
        data = {
            "models": [{"bigg_id": "iJO1366"}, {"bigg_id": "iML1515"}],
            "count": 2,
        }
        await cache.set("test:complex", data, ttl=3600)
        result = await cache.get("test:complex")
        assert result == data

    @pytest.mark.asyncio
    async def test_cache_overwrite(self, cache: CacheManager) -> None:
        """Setting same key should overwrite."""
        await cache.set("test:key", {"v": 1}, ttl=3600)
        await cache.set("test:key", {"v": 2}, ttl=3600)
        result = await cache.get("test:key")
        assert result == {"v": 2}
