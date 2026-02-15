"""Tests for cache manager."""

import pytest

from src.cache.cache_manager import CacheManager


class TestCacheManager:
    @pytest.fixture
    async def cache(self, tmp_path):
        db_path = tmp_path / "test_cache.db"
        cm = CacheManager(db_path=db_path)
        await cm.initialize()
        yield cm
        await cm.close()

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("test_key", {"foo": "bar"})
        result = await cache.get("test_key")
        assert result == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_get_missing(self, cache):
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_entry(self, cache):
        import time

        # Set with TTL=1, then wait for it to expire
        await cache.set("expired_key", "value", ttl=1)
        time.sleep(1.1)
        result = await cache.get("expired_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        await cache.set("del_key", "value")
        await cache.delete("del_key")
        result = await cache.get("del_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        await cache.set("k1", "v1")
        await cache.set("k2", "v2")
        count = await cache.clear()
        assert count == 2
        assert await cache.get("k1") is None

    @pytest.mark.asyncio
    async def test_clear_by_source(self, cache):
        await cache.set("k1", "v1", source="bigg")
        await cache.set("k2", "v2", source="kegg")
        count = await cache.clear(source="bigg")
        assert count == 1
        assert await cache.get("k1") is None
        assert await cache.get("k2") is not None

    @pytest.mark.asyncio
    async def test_stats(self, cache):
        await cache.set("s1", "v1")
        await cache.set("s2", "v2")
        stats = await cache.stats()
        assert stats["total"] == 2
        assert stats["active"] == 2

    @pytest.mark.asyncio
    async def test_string_value(self, cache):
        await cache.set("str_key", "plain string value")
        result = await cache.get("str_key")
        assert result == "plain string value"

    @pytest.mark.asyncio
    async def test_overwrite(self, cache):
        await cache.set("ow_key", "original")
        await cache.set("ow_key", "updated")
        result = await cache.get("ow_key")
        assert result == "updated"

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, cache):
        import time

        await cache.set("exp_key", "value", ttl=1)
        await cache.set("fresh_key", "value", ttl=3600)
        time.sleep(1.1)
        count = await cache.cleanup_expired()
        assert count >= 1
        assert await cache.get("exp_key") is None
        assert await cache.get("fresh_key") is not None

    @pytest.mark.asyncio
    async def test_large_dict_value(self, cache):
        large_data = {f"key_{i}": f"value_{i}" for i in range(100)}
        await cache.set("large_key", large_data)
        result = await cache.get("large_key")
        assert len(result) == 100

    @pytest.mark.asyncio
    async def test_list_value(self, cache):
        await cache.set("list_key", [1, 2, 3, "four"])
        result = await cache.get("list_key")
        assert result == [1, 2, 3, "four"]

    @pytest.mark.asyncio
    async def test_get_before_init(self):
        """Get on uninitialized cache returns None."""
        cm = CacheManager(db_path=None)
        result = await cm.get("any_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_before_init(self):
        """Set on uninitialized cache is a no-op."""
        cm = CacheManager(db_path=None)
        await cm.set("any_key", "value")  # should not raise

    @pytest.mark.asyncio
    async def test_stats_with_expired(self, cache):
        import time

        await cache.set("exp1", "v1", ttl=1)
        await cache.set("fresh1", "v1", ttl=3600)
        time.sleep(1.1)
        stats = await cache.stats()
        assert stats["total"] == 2
        assert stats["expired"] >= 1
        assert stats["active"] >= 1
