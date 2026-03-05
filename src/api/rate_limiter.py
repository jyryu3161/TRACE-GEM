"""Token-bucket rate limiter for API clients."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket rate limiter for controlling API request rates."""

    def __init__(self, rate: float, burst: int = 1) -> None:
        """
        Args:
            rate: Requests per second allowed.
            burst: Maximum burst size (tokens available at once).
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate wait time for next token
                wait = (1.0 - self._tokens) / self._rate
            # Sleep OUTSIDE the lock so other coroutines aren't blocked
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now
