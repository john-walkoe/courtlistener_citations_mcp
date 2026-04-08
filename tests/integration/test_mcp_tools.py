"""
Integration tests for courtlistener_mcp.main.

Covers:
- _handle_client_errors decorator: error conversion and pass-through
- AuthenticationError propagates; client pool is unchanged (multi-tenant: one
  user's auth failure does not evict other users' cached clients)
- Non-auth ToolError does NOT disturb the client pool
- Concurrent _get_client() calls for the same token produce a single instance
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

import courtlistener_mcp.main as main_module
from courtlistener_mcp.api.client import CourtListenerClient
from courtlistener_mcp.errors import AuthenticationError, NotFoundError


# =============================================================================
# Helpers
# =============================================================================


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Build a minimal httpx.HTTPStatusError with the given status code."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=MagicMock(spec=httpx.Request),
        response=mock_response,
    )


def _decorated(fn):
    """Apply _handle_client_errors to a plain coroutine for testing."""
    return main_module._handle_client_errors(fn)


# =============================================================================
# _handle_client_errors pass-through and conversion
# =============================================================================


class TestHandleClientErrors:
    """Verify that _handle_client_errors converts exceptions correctly."""

    async def test_handle_client_errors_passes_through_tool_error(self):
        """A ToolError raised inside the decorated function must be re-raised unchanged."""
        original_error = ToolError("original tool error message")

        @_decorated
        async def fn():
            raise original_error

        with pytest.raises(ToolError) as exc_info:
            await fn()

        assert exc_info.value is original_error

    async def test_handle_client_errors_converts_value_error(self):
        """ValueError must be converted to ToolError carrying the original message."""
        @_decorated
        async def fn():
            raise ValueError("bad input value")

        with pytest.raises(ToolError, match="bad input value"):
            await fn()

    async def test_handle_client_errors_converts_timeout(self):
        """httpx.TimeoutException must become a ToolError mentioning 'timed out'."""
        @_decorated
        async def fn():
            raise httpx.TimeoutException("connection timed out")

        with pytest.raises(ToolError, match="timed out"):
            await fn()

    async def test_handle_client_errors_converts_request_error(self):
        """httpx.RequestError (e.g. ConnectError) must become a ToolError mentioning 'Cannot reach'."""
        @_decorated
        async def fn():
            raise httpx.ConnectError("connection refused")

        with pytest.raises(ToolError, match="Cannot reach"):
            await fn()

    async def test_handle_client_errors_converts_401_httpstatus(self):
        """HTTPStatusError with status 401 must produce a ToolError mentioning 'invalid or expired'."""
        @_decorated
        async def fn():
            raise _make_http_status_error(401)

        with pytest.raises(ToolError, match="invalid or expired"):
            await fn()

    async def test_handle_client_errors_converts_403_httpstatus(self):
        """HTTPStatusError with status 403 must produce a ToolError mentioning 'permission'."""
        @_decorated
        async def fn():
            raise _make_http_status_error(403)

        with pytest.raises(ToolError, match="permission"):
            await fn()

    async def test_handle_client_errors_converts_404_httpstatus(self):
        """HTTPStatusError with status 404 must produce a ToolError mentioning 'not found'."""
        @_decorated
        async def fn():
            raise _make_http_status_error(404)

        with pytest.raises(ToolError, match="not found"):
            await fn()

    async def test_handle_client_errors_converts_generic_5xx_httpstatus(self):
        """Any other HTTPStatusError should produce a generic ToolError with the status code."""
        @_decorated
        async def fn():
            raise _make_http_status_error(503)

        with pytest.raises(ToolError, match="503"):
            await fn()

    async def test_handle_client_errors_returns_value_on_success(self):
        """When no exception is raised, the return value passes through unchanged."""
        @_decorated
        async def fn():
            return "success result"

        result = await fn()
        assert result == "success result"


# =============================================================================
# Auth error handling with multi-tenant client pool
# =============================================================================


class TestClientResetOnAuthError:
    """
    AuthenticationError propagates to the caller. In multi-tenant mode, one
    user's bad token does not evict other users' cached clients from the pool.
    """

    async def test_auth_error_propagates(self):
        """AuthenticationError must re-raise unchanged through the decorator."""
        @_decorated
        async def fn():
            raise AuthenticationError("token expired")

        with pytest.raises(AuthenticationError):
            await fn()

    async def test_auth_error_does_not_clear_pool(self):
        """
        An AuthenticationError must not disturb other users' pool entries.
        Multi-tenant: one bad token is isolated; other users' clients remain cached.
        """
        sentinel = MagicMock(spec=CourtListenerClient)
        main_module._client_pool["other_user_key"] = sentinel

        @_decorated
        async def fn():
            raise AuthenticationError("token expired")

        with pytest.raises(AuthenticationError):
            await fn()

        assert main_module._client_pool.get("other_user_key") is sentinel

    async def test_non_auth_tool_error_does_not_disturb_pool(self):
        """A non-auth ToolError must not disturb the client pool."""
        sentinel = MagicMock(spec=CourtListenerClient)
        main_module._client_pool["some_key"] = sentinel

        @_decorated
        async def fn():
            raise NotFoundError("case not found")

        with pytest.raises(NotFoundError):
            await fn()

        assert main_module._client_pool.get("some_key") is sentinel


# =============================================================================
# Concurrent client initialisation (audit fix 1)
# =============================================================================


class TestConcurrentClientInit:
    """
    Multiple concurrent calls to _get_client() with the same token must produce
    exactly ONE CourtListenerClient (pool lock prevents double-init).
    Different tokens produce independent clients.
    """

    async def test_concurrent_calls_same_token_creates_single_instance(self):
        """
        Three concurrent _get_client() calls for the same token must each
        receive the same instance — constructor called exactly once.
        """
        main_module._client_pool.clear()
        main_module._client_pool_lock = None

        construction_count = 0
        created_instance = None

        class TrackingClient:
            def __init__(self, token: str, circuit_breaker=None):
                nonlocal construction_count, created_instance
                construction_count += 1
                created_instance = self

        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = "test_token_12345678901234567890"

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            with patch("courtlistener_mcp.main.CourtListenerClient", TrackingClient):
                with patch("courtlistener_mcp.main.get_http_request", side_effect=RuntimeError):
                    results = await asyncio.gather(
                        main_module._get_client(),
                        main_module._get_client(),
                        main_module._get_client(),
                    )

        assert construction_count == 1
        assert results[0] is results[1]
        assert results[1] is results[2]
        assert results[0] is created_instance

    async def test_get_client_raises_tool_error_without_token(self):
        """No token from any source must raise a ToolError with setup guidance."""
        main_module._client_pool.clear()
        main_module._client_pool_lock = None

        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = None

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            with patch("courtlistener_mcp.main.get_http_request", side_effect=RuntimeError):
                with pytest.raises(ToolError, match="X-CourtListener-Token"):
                    await main_module._get_client(ctx=None)

    async def test_pool_returns_cached_client_for_same_token(self):
        """Same token on a second call returns the already-cached client without reconstruction."""
        main_module._client_pool.clear()
        main_module._client_pool_lock = None

        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = "test_token_12345678901234567890"

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            with patch("courtlistener_mcp.main.get_http_request", side_effect=RuntimeError):
                first = await main_module._get_client()
                second = await main_module._get_client()

        assert first is second
