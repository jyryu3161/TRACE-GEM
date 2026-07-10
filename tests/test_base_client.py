"""Tests for base API client (retry, circuit breaker, caching, rate limiting)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.base_client import APIUnavailableError, BaseAPIClient
from src.core.models import EvidenceItem, Reaction


class ConcreteClient(BaseAPIClient):
    """Concrete implementation for testing the abstract base."""

    async def check_evidence(self, reaction: Reaction, **kwargs) -> list[EvidenceItem]:
        return []


class TestBaseClientInit:
    def test_init(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=5.0,
        )
        assert client.name == "test"
        assert client.base_url == "https://example.com"
        assert client._max_retries == 3

    def test_base_url_trailing_slash_stripped(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com/",
            rate=1.0,
        )
        assert client.base_url == "https://example.com"

    def test_custom_max_retries(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
            max_retries=5,
        )
        assert client._max_retries == 5

    def test_initial_circuit_state(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        assert client._circuit_open is False
        assert client._failure_count == 0


class TestBaseClientSession:
    @pytest.mark.asyncio
    async def test_get_session_creates(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        session = await client._get_session()
        assert session is not None
        assert not session.closed
        await client.close()

    @pytest.mark.asyncio
    async def test_close_session(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        await client._get_session()
        await client.close()
        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_when_no_session(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        await client.close()  # should not raise


class TestCircuitBreaker:
    def test_circuit_opens_after_failures(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        client._failure_count = 4
        # Simulate one more failure
        client._failure_count += 1
        if client._failure_count >= 5:
            client._circuit_open = True
            client._circuit_open_until = time.monotonic() + 300
        assert client._circuit_open is True

    @pytest.mark.asyncio
    async def test_circuit_blocks_requests(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        client._circuit_open = True
        client._circuit_open_until = time.monotonic() + 300
        # An open circuit means "unavailable", not "not found": raise rather
        # than return None so callers don't record it as absent evidence.
        with pytest.raises(APIUnavailableError):
            await client.get("/test")

    @pytest.mark.asyncio
    async def test_circuit_resets_after_timeout(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        client._circuit_open = True
        client._circuit_open_until = time.monotonic() - 1  # already expired
        client._failure_count = 5

        # Mock the rate limiter and session
        client._rate_limiter = MagicMock()
        client._rate_limiter.acquire = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        client._session = mock_session

        await client.get("/test")
        assert client._circuit_open is False
        assert client._failure_count == 0


class TestBaseClientCaching:
    @pytest.mark.asyncio
    async def test_returns_cached_value(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value={"cached": True})

        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
            cache_manager=cache,
        )
        result = await client.get("/test", cache_key="k1")
        assert result == {"cached": True}

    @pytest.mark.asyncio
    async def test_cache_miss_makes_request(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()

        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
            cache_manager=cache,
        )
        client._rate_limiter = MagicMock()
        client._rate_limiter.acquire = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content_type = "application/json"
        mock_resp.json = AsyncMock(return_value={"data": "value"})

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        client._session = mock_session

        result = await client.get("/test", cache_key="k1")
        assert result == {"data": "value"}
        cache.set.assert_awaited_once()


class TestBaseClientRetry:
    @pytest.mark.asyncio
    async def test_retries_on_server_error(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
            max_retries=2,
        )
        client._rate_limiter = MagicMock()
        client._rate_limiter.acquire = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.content_type = "text/html"

        call_count = 0

        def make_ctx(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(side_effect=make_ctx)
        client._session = mock_session

        with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(APIUnavailableError):
            await client.get("/test")

        # Exhausted retries surface as unavailable (unknown), not absent.
        assert call_count == 2  # max_retries=2

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        client._rate_limiter = MagicMock()
        client._rate_limiter.acquire = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 404

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        client._session = mock_session

        result = await client.get("/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_text_response(self):
        client = ConcreteClient(
            name="test",
            base_url="https://example.com",
            rate=1.0,
        )
        client._rate_limiter = MagicMock()
        client._rate_limiter.acquire = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content_type = "text/plain"
        mock_resp.text = AsyncMock(return_value="plain text response")

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        client._session = mock_session

        result = await client.get("/test")
        assert result == "plain text response"
