"""Base API client with rate limiting, retry, and caching."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

import aiohttp

from src.api.rate_limiter import RateLimiter
from src.core.models import EvidenceItem, Reaction

logger = logging.getLogger("gem_evaluator.api")


class BaseAPIClient(ABC):
    """Abstract base class for all external API clients.

    Provides: rate limiting, exponential backoff retry, response caching.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        rate: float,
        cache_manager=None,
        max_retries: int = 3,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._rate_limiter = RateLimiter(rate=rate, burst=max(1, int(rate)))
        self._cache = cache_manager
        self._max_retries = max_retries
        self._session: aiohttp.ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None
        self._failure_count = 0
        self._circuit_open = False
        self._circuit_open_until = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        current_loop = asyncio.get_running_loop()
        if (
            self._session is None
            or self._session.closed
            or self._session_loop is not current_loop
        ):
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception:
                    pass
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._session_loop = current_loop
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get(
        self,
        path: str,
        params: dict | None = None,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
    ) -> dict | str | None:
        """Make a GET request with rate limiting, caching, and retry."""
        # Circuit breaker check
        if self._circuit_open:
            if time.monotonic() < self._circuit_open_until:
                logger.warning("[%s] Circuit open, skipping request", self.name)
                return None
            self._circuit_open = False
            self._failure_count = 0

        # Check cache first
        if cache_key and self._cache:
            cached: dict | str | None = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Rate limit
        await self._rate_limiter.acquire()

        url = f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

        for attempt in range(self._max_retries):
            try:
                session = await self._get_session()
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        content_type = resp.content_type or ""
                        data: dict | str
                        if "json" in content_type:
                            data = await resp.json()
                        else:
                            data = await resp.text()

                        # Cache the result
                        if cache_key and self._cache:
                            await self._cache.set(cache_key, data, ttl=cache_ttl)

                        self._failure_count = 0
                        return data

                    if resp.status == 404:
                        return None

                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", 5))
                        logger.warning("[%s] Rate limited, waiting %.1fs", self.name, retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    logger.warning("[%s] HTTP %d for %s", self.name, resp.status, url)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    "[%s] Request failed (attempt %d/%d): %s",
                    self.name,
                    attempt + 1,
                    self._max_retries,
                    e,
                )

            # Exponential backoff
            if attempt < self._max_retries - 1:
                wait = 2**attempt
                await asyncio.sleep(wait)

        # Track failures for circuit breaker
        self._failure_count += 1
        if self._failure_count >= 5:
            self._circuit_open = True
            self._circuit_open_until = time.monotonic() + 300  # 5 min
            logger.error(
                "[%s] Circuit breaker opened after %d failures",
                self.name,
                self._failure_count,
            )

        return None

    @abstractmethod
    async def check_evidence(self, reaction: Reaction, **kwargs) -> list[EvidenceItem]:
        """Check for evidence of a reaction in this database."""
        ...
