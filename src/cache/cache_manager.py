"""SQLite-based cache manager for API responses."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

from src.cache.schema import SCHEMA_SQL
from src.utils.constants import API_CACHE_TTL, CACHE_DB_PATH, CONFIG_DIR

logger = logging.getLogger("metataskgapfill.cache")


class CacheManager:
    """Persistent SQLite cache for API responses and ID mappings."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or CACHE_DB_PATH
        self._db: aiosqlite.Connection | None = None
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        self._bound_loop = asyncio.get_running_loop()
        logger.info("Cache initialized at %s", self._db_path)

    async def _ensure_connection(self) -> None:
        """Reconnect if the event loop has changed since initialization."""
        current_loop = asyncio.get_running_loop()
        if self._bound_loop is not current_loop:
            logger.info("Event loop changed, reconnecting cache DB")
            # Old connection is unusable on this loop; don't await close
            self._db = await aiosqlite.connect(str(self._db_path))
            self._bound_loop = current_loop

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        self._bound_loop = None

    async def get(self, key: str) -> Any | None:
        """Get a cached value if it exists and is not expired."""
        if not self._db:
            return None
        await self._ensure_connection()

        async with self._db.execute(
            "SELECT value, created_at, ttl FROM api_cache WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None

            value_str, created_at, ttl = row
            if time.time() - created_at > ttl:
                # Expired — delete and return None
                await self._db.execute("DELETE FROM api_cache WHERE key = ?", (key,))
                await self._db.commit()
                return None

            try:
                return json.loads(value_str)
            except json.JSONDecodeError:
                return value_str

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        source: str | None = None,
    ) -> None:
        """Store a value in the cache."""
        if not self._db:
            return
        await self._ensure_connection()

        ttl = ttl or API_CACHE_TTL
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, default=str)
        else:
            value_str = str(value)

        await self._db.execute(
            """INSERT OR REPLACE INTO api_cache (key, value, created_at, ttl, source)
               VALUES (?, ?, ?, ?, ?)""",
            (key, value_str, time.time(), ttl, source),
        )
        await self._db.commit()

    async def delete(self, key: str) -> None:
        """Delete a specific cache entry."""
        if not self._db:
            return
        await self._ensure_connection()
        await self._db.execute("DELETE FROM api_cache WHERE key = ?", (key,))
        await self._db.commit()

    async def clear(self, source: str | None = None) -> int:
        """Clear cache entries. If source given, only clear that source."""
        if not self._db:
            return 0
        await self._ensure_connection()

        if source:
            cursor = await self._db.execute("DELETE FROM api_cache WHERE source = ?", (source,))
        else:
            cursor = await self._db.execute("DELETE FROM api_cache")

        await self._db.commit()
        count = cursor.rowcount
        logger.info(
            "Cleared %d cache entries%s", count, f" for source '{source}'" if source else ""
        )
        return count

    async def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        if not self._db:
            return 0
        await self._ensure_connection()

        cursor = await self._db.execute(
            "DELETE FROM api_cache WHERE (? - created_at) > ttl",
            (time.time(),),
        )
        await self._db.commit()
        count = cursor.rowcount
        if count:
            logger.info("Cleaned up %d expired cache entries", count)
        return count

    async def stats(self) -> dict:
        """Get cache statistics."""
        if not self._db:
            return {"total": 0, "expired": 0}
        await self._ensure_connection()

        now = time.time()
        async with self._db.execute("SELECT COUNT(*) FROM api_cache") as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        async with self._db.execute(
            "SELECT COUNT(*) FROM api_cache WHERE (? - created_at) > ttl", (now,)
        ) as cursor:
            row = await cursor.fetchone()
            expired = row[0] if row else 0

        return {"total": total, "active": total - expired, "expired": expired}
