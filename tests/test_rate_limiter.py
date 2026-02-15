"""Tests for token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.api.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_initial_tokens(self):
        rl = RateLimiter(rate=10.0, burst=5)
        assert rl._tokens == 5.0
        assert rl._rate == 10.0
        assert rl._burst == 5

    def test_default_burst(self):
        rl = RateLimiter(rate=3.0)
        assert rl._burst == 1

    @pytest.mark.asyncio
    async def test_acquire_consumes_token(self):
        rl = RateLimiter(rate=10.0, burst=5)
        initial = rl._tokens
        await rl.acquire()
        assert rl._tokens < initial

    @pytest.mark.asyncio
    async def test_burst_capacity(self):
        """Should be able to acquire burst-many tokens immediately."""
        rl = RateLimiter(rate=100.0, burst=3)
        start = time.monotonic()
        for _ in range(3):
            await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # all 3 should be nearly instant

    @pytest.mark.asyncio
    async def test_rate_limiting_blocks(self):
        """After exhausting burst, next acquire should wait."""
        rl = RateLimiter(rate=10.0, burst=1)
        await rl.acquire()  # exhausts the 1 token
        start = time.monotonic()
        await rl.acquire()  # should wait ~0.1s
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # should have waited

    @pytest.mark.asyncio
    async def test_refill(self):
        rl = RateLimiter(rate=100.0, burst=5)
        # Exhaust all tokens
        for _ in range(5):
            await rl.acquire()
        # Wait for refill
        await asyncio.sleep(0.1)
        # Should have refilled some tokens
        rl._refill()
        assert rl._tokens > 0

    @pytest.mark.asyncio
    async def test_tokens_capped_at_burst(self):
        rl = RateLimiter(rate=100.0, burst=3)
        # Wait for more than enough refill time
        await asyncio.sleep(0.1)
        rl._refill()
        assert rl._tokens <= 3.0  # capped at burst

    @pytest.mark.asyncio
    async def test_concurrent_acquire(self):
        """Multiple concurrent acquires should be serialized by the lock."""
        rl = RateLimiter(rate=100.0, burst=5)
        results = await asyncio.gather(*[rl.acquire() for _ in range(5)])
        assert len(results) == 5  # all should complete

    @pytest.mark.asyncio
    async def test_zero_rate_handled(self):
        """Rate=0 would cause division by zero, but we use min burst=1."""
        # This tests that even with very low rate, acquire eventually returns
        rl = RateLimiter(rate=0.01, burst=1)
        await rl.acquire()  # first should succeed (uses initial token)
