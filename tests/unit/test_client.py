"""
Unit tests for courtlistener_mcp.api.client.

Tests cover:
- RateLimiter token-bucket behaviour
- _chunk_text splitting logic
- _parse_throttle_wait parsing logic
- _validate_search_params validation
- CourtListenerClient._request() HTTP interactions
- CourtListenerClient.validate_citations() text handling
- Security audit logging (401, 403, 429)

Mocking strategy:
  respx.MockRouter + httpx.MockTransport(router.handler) is injected directly
  into CourtListenerClient._client so we intercept real httpx.AsyncClient calls
  without needing the respx.mock context manager (which does NOT auto-patch
  pre-created AsyncClient instances in respx 0.22).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from courtlistener_mcp.api.client import (
    CourtListenerClient,
    RateLimiter,
    _chunk_text,
    _parse_throttle_wait,
    _validate_search_params,
    security_logger,
)
from courtlistener_mcp.config.api_constants import (
    API_BASE_URL,
    CITATION_MAX_TEXT_LENGTH,
    DEFAULT_MAX_RETRIES,
    MAX_QUERY_LENGTH,
    MAX_VALIDATE_TEXT_LENGTH,
)
from courtlistener_mcp.errors import AuthenticationError, NotFoundError


# ---------------------------------------------------------------------------
# Shared helper: build a CourtListenerClient with a respx-mocked transport
# ---------------------------------------------------------------------------

def _make_mocked_client(router: respx.MockRouter) -> CourtListenerClient:
    """
    Return a CourtListenerClient whose internal httpx.AsyncClient uses
    the supplied respx MockRouter as its transport.
    """
    client = CourtListenerClient(token="test_token_12345678901234567890")
    client._client = httpx.AsyncClient(
        base_url=API_BASE_URL,
        headers={
            "Authorization": "Token test_token_12345678901234567890",
            "Accept": "application/json",
            "User-Agent": "CourtListener-MCP/1.0",
        },
        transport=httpx.MockTransport(router.handler),
    )
    return client


# =============================================================================
# RateLimiter tests
# =============================================================================


class TestRateLimiter:
    """Tests for the token-bucket RateLimiter."""

    def test_rate_limiter_has_full_tokens_initially(self):
        """A new RateLimiter starts with max_per_minute tokens."""
        limiter = RateLimiter(max_per_minute=10)
        assert limiter._tokens == 10.0

    async def test_rate_limiter_does_not_sleep_when_tokens_available(self):
        """First N acquires within burst budget should never sleep."""
        limiter = RateLimiter(max_per_minute=10)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            for _ in range(10):
                await limiter.acquire()
            mock_sleep.assert_not_called()

    async def test_rate_limiter_throttles_on_empty_bucket(self):
        """Once all tokens are consumed the next acquire must sleep."""
        limiter = RateLimiter(max_per_minute=2)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Drain tokens
            await limiter.acquire()
            await limiter.acquire()
            # Bucket is empty; next acquire should sleep
            await limiter.acquire()
            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] > 0


# =============================================================================
# _chunk_text tests
# =============================================================================


class TestChunkText:
    """Tests for the _chunk_text helper."""

    def test_chunk_text_no_chunk_needed(self):
        """Text shorter than the limit is returned as a single-element list."""
        text = "Short text."
        result = _chunk_text(text, max_length=100)
        assert result == ["Short text."]

    def test_chunk_text_splits_at_sentence_boundary(self):
        """Long text should split at the last '. ' before the boundary."""
        sentence_a = "First sentence. "
        sentence_b = "B" * 60
        text = sentence_a + sentence_b
        limit = len(sentence_a) + 20
        chunks = _chunk_text(text, max_length=limit)
        assert len(chunks) >= 2
        # The first chunk must end at the sentence boundary
        assert chunks[0].endswith(". ") or chunks[0].endswith(".")

    def test_chunk_text_splits_at_space_fallback(self):
        """When there's no '. ' near the boundary, split at the last space."""
        words = " ".join(["word"] * 40)  # words with spaces, no periods
        limit = 50
        chunks = _chunk_text(words, max_length=limit)
        assert len(chunks) > 1

    def test_chunk_text_returns_empty_list_for_empty_string(self):
        """Empty input should produce an empty list (whitespace-only stripped)."""
        result = _chunk_text("", max_length=100)
        assert result == []

    def test_chunk_text_each_chunk_respects_max_length(self):
        """Every produced chunk should be at most max_length characters."""
        import random
        random.seed(42)
        text = ("Hello world. " * 50) + ("x" * 200)
        limit = 128
        chunks = _chunk_text(text, max_length=limit)
        for chunk in chunks:
            assert len(chunk) <= limit + 1, f"Chunk too long: {len(chunk)} > {limit}"


# =============================================================================
# _parse_throttle_wait tests
# =============================================================================


class TestParseThrottleWait:
    """Tests for _parse_throttle_wait helper."""

    def _make_response(self, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
        """Build a minimal httpx.Response for testing."""
        import json as _json
        content = _json.dumps(body or {}).encode()
        return httpx.Response(
            status_code=429,
            headers=headers or {},
            content=content,
        )

    def test_parse_throttle_wait_uses_wait_until(self):
        """A wait_until datetime in the future should produce a positive wait."""
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
        body = {"wait_until": future.isoformat()}
        response = self._make_response(body=body)
        wait = _parse_throttle_wait(response)
        assert wait > 0

    def test_parse_throttle_wait_uses_retry_after_header(self):
        """When no wait_until in body, fall back to Retry-After header."""
        response = self._make_response(body={}, headers={"Retry-After": "30"})
        wait = _parse_throttle_wait(response)
        assert wait == 30.0

    def test_parse_throttle_wait_returns_default(self):
        """With no wait_until and no Retry-After, return 60.0 seconds."""
        response = self._make_response(body={}, headers={})
        wait = _parse_throttle_wait(response)
        assert wait == 60.0

    def test_parse_throttle_wait_minimum_is_one_second(self):
        """If wait_until is already in the past the result should be >= 1.0."""
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        body = {"wait_until": past.isoformat()}
        response = self._make_response(body=body)
        wait = _parse_throttle_wait(response)
        assert wait >= 1.0


# =============================================================================
# _validate_search_params tests
# =============================================================================


class TestValidateSearchParams:
    """Tests for _validate_search_params."""

    def test_validate_search_params_accepts_valid_date(self):
        """A correctly formatted YYYY-MM-DD date should not raise."""
        _validate_search_params(date_filed_after="2024-03-01")  # no exception

    def test_validate_search_params_rejects_invalid_date_format(self):
        """Human-readable dates should raise ValueError mentioning YYYY-MM-DD."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _validate_search_params(date_filed_after="March 2024")

    def test_validate_search_params_rejects_oversized_query(self):
        """Queries longer than MAX_QUERY_LENGTH should raise ValueError."""
        long_query = "x" * (MAX_QUERY_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds"):
            _validate_search_params(query=long_query)

    def test_validate_search_params_allows_none_params(self):
        """All-None params should succeed without raising."""
        _validate_search_params(query=None, date_filed_after=None, date_filed_before=None)

    def test_validate_search_params_rejects_invalid_before_date(self):
        """An invalid date_filed_before should raise ValueError."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _validate_search_params(date_filed_before="01/01/2024")

    def test_validate_search_params_accepts_boundary_query_length(self):
        """A query of exactly MAX_QUERY_LENGTH chars should be accepted."""
        _validate_search_params(query="q" * MAX_QUERY_LENGTH)


# =============================================================================
# CourtListenerClient._request() tests
# =============================================================================


class TestClientRequest:
    """Tests for CourtListenerClient._request using injected respx mocks."""

    async def test_request_returns_json_on_200(self):
        """A 200 response should return the parsed JSON dict."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/search/")
        assert result == {"results": []}

    async def test_request_raises_authentication_error_on_401(self):
        """A 401 response should raise AuthenticationError."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid token"})
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(AuthenticationError):
                await client._request("GET", "/search/")

    async def test_request_raises_authentication_error_on_403(self):
        """A 403 response should raise AuthenticationError."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(
            return_value=httpx.Response(403, json={"detail": "Forbidden"})
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(AuthenticationError):
                await client._request("GET", "/search/")

    async def test_request_raises_not_found_error_on_404(self):
        """A 404 response should raise NotFoundError."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/clusters/99999/").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(NotFoundError):
                await client._request("GET", "/clusters/99999/")

    async def test_request_retries_on_500_and_succeeds(self):
        """A 500 followed by a 200 should return the successful result after one retry."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, json={"error": "server error"})
            return httpx.Response(200, json={"results": ["ok"]})

        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(side_effect=side_effect)
        client = _make_mocked_client(router)

        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/search/")

        assert result == {"results": ["ok"]}
        assert call_count == 2

    async def test_request_raises_after_max_retries_on_500(self):
        """Persistent 500 responses should raise after DEFAULT_MAX_RETRIES attempts."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, json={"error": "server error"})

        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(side_effect=side_effect)
        client = _make_mocked_client(router)

        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
                await client._request("GET", "/search/")

        assert call_count == DEFAULT_MAX_RETRIES

    async def test_request_retries_on_429_and_succeeds(self):
        """429 responses should be retried; a subsequent 200 should succeed."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(429, json={}, headers={"Retry-After": "1"})
            return httpx.Response(200, json={"results": ["found"]})

        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(side_effect=side_effect)
        client = _make_mocked_client(router)

        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/search/")

        assert result == {"results": ["found"]}
        assert call_count == 3


# =============================================================================
# CourtListenerClient.validate_citations() tests
# =============================================================================


class TestValidateCitations:
    """Tests for CourtListenerClient.validate_citations."""

    async def test_validate_citations_returns_empty_for_blank_text(self):
        """Empty string input should return an empty list without any HTTP call."""
        client = CourtListenerClient(token="test_token_12345678901234567890")
        result = await client.validate_citations("")
        assert result == []

    async def test_validate_citations_returns_empty_for_whitespace(self):
        """Whitespace-only input should return an empty list."""
        client = CourtListenerClient(token="test_token_12345678901234567890")
        result = await client.validate_citations("   ")
        assert result == []

    async def test_validate_citations_rejects_oversized_text(self):
        """Text exceeding MAX_VALIDATE_TEXT_LENGTH should raise ValueError."""
        client = CourtListenerClient(token="test_token_12345678901234567890")
        oversized = "x" * (MAX_VALIDATE_TEXT_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            await client.validate_citations(oversized)

    async def test_validate_citations_returns_results_on_success(self):
        """A successful POST to /citation-lookup/ should return the result list."""
        payload = [{"citation": "573 U.S. 208", "status": 200}]
        router = respx.MockRouter(assert_all_called=False)
        router.post(f"{API_BASE_URL}/citation-lookup/").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.validate_citations("See 573 U.S. 208.")
        assert result == payload

    async def test_validate_citations_chunks_large_text(self):
        """Text exceeding CITATION_MAX_TEXT_LENGTH should be split and POST called twice."""
        # Build text slightly more than CITATION_MAX_TEXT_LENGTH using "word " units
        unit = "word " * (CITATION_MAX_TEXT_LENGTH // 5 + 1)
        large_text = unit[: CITATION_MAX_TEXT_LENGTH + 500]

        post_call_count = 0

        def citation_side_effect(request):
            nonlocal post_call_count
            post_call_count += 1
            return httpx.Response(200, json=[])

        router = respx.MockRouter(assert_all_called=False)
        router.post(f"{API_BASE_URL}/citation-lookup/").mock(
            side_effect=citation_side_effect
        )
        client = _make_mocked_client(router)
        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            await client.validate_citations(large_text)

        assert post_call_count == 2


# =============================================================================
# Security logging tests
# =============================================================================


import contextlib
from typing import Generator


@contextlib.contextmanager
def _capture_security_log() -> Generator[list, None, None]:
    """
    Context manager that temporarily enables caplog-style capture on the
    'security' logger.

    The security logger has propagate=False (set by setup_logging() at import
    time so it writes to a dedicated file, not the root logger).  pytest's
    caplog works via the root handler, so we must temporarily add our own
    in-memory handler AND re-enable propagation while the test runs.
    """
    sec_logger = logging.getLogger("security")
    records: list[logging.LogRecord] = []

    class _CollectHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _CollectHandler(level=logging.WARNING)
    old_propagate = sec_logger.propagate
    sec_logger.addHandler(handler)
    sec_logger.propagate = False  # keep it False; we collect with our handler
    try:
        yield records
    finally:
        sec_logger.removeHandler(handler)
        sec_logger.propagate = old_propagate


class TestSecurityLogging:
    """Tests that verify the security audit logger fires for critical events."""

    async def test_401_logs_to_security_logger(self):
        """A 401 response must emit a WARNING on the 'security' logger."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid token"})
        )
        client = _make_mocked_client(router)

        with _capture_security_log() as records:
            with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(AuthenticationError):
                    await client._request("GET", "/search/")

        assert len(records) >= 1
        combined = " ".join(r.getMessage() for r in records).lower()
        assert "401" in combined or "invalid" in combined

    async def test_403_logs_to_security_logger(self):
        """A 403 response must emit a WARNING on the 'security' logger."""
        router = respx.MockRouter(assert_all_called=False)
        router.get(f"{API_BASE_URL}/search/").mock(
            return_value=httpx.Response(403, json={"detail": "Forbidden"})
        )
        client = _make_mocked_client(router)

        with _capture_security_log() as records:
            with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(AuthenticationError):
                    await client._request("GET", "/search/")

        assert len(records) >= 1
        combined = " ".join(r.getMessage() for r in records).lower()
        assert "403" in combined or "permission" in combined

    async def test_citation_429_logs_to_security_logger(self):
        """
        When /citation-lookup/ returns 429 on every attempt the security logger
        must record a rate-limit warning.
        """
        router = respx.MockRouter(assert_all_called=False)
        router.post(f"{API_BASE_URL}/citation-lookup/").mock(
            return_value=httpx.Response(
                429, json={}, headers={"Retry-After": "1"}
            )
        )
        client = _make_mocked_client(router)

        with _capture_security_log() as records:
            with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
                from courtlistener_mcp.errors import RateLimitError
                with pytest.raises(RateLimitError):
                    await client.validate_citations("See 573 U.S. 208.")

        assert len(records) >= 1
        combined = " ".join(r.getMessage() for r in records).lower()
        assert "rate limit" in combined or "throttle" in combined or "429" in combined

    def test_security_logger_defined_at_module_level(self):
        """The client module must export a module-level 'security' logger."""
        import courtlistener_mcp.api.client as client_module
        assert hasattr(client_module, "security_logger")
        assert client_module.security_logger.name == "security"
