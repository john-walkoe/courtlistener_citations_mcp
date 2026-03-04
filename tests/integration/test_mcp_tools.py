"""
Integration tests for courtlistener_mcp.main.

Covers:
- _handle_client_errors decorator: error conversion and pass-through
- AuthenticationError resets _client to None (audit fix 2)
- Non-auth ToolError does NOT reset _client
- Concurrent _get_client() calls produce a single CourtListenerClient (audit fix 1)
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
# _client reset on AuthenticationError (audit fix 2)
# =============================================================================


class TestClientResetOnAuthError:
    """AuthenticationError must reset _client to None so the next call re-initialises."""

    async def test_auth_error_resets_client_to_none(self):
        """
        When a decorated function raises AuthenticationError, main._client must
        be set to None after the exception propagates.
        """
        main_module._client = MagicMock(spec=CourtListenerClient)

        @_decorated
        async def fn():
            raise AuthenticationError("token expired")

        with pytest.raises(AuthenticationError):
            await fn()

        assert main_module._client is None

    async def test_non_auth_tool_error_does_not_reset_client(self):
        """
        A ToolError that is NOT an AuthenticationError (e.g. NotFoundError) must
        NOT reset _client — only auth failures should clear the cached client.
        """
        sentinel_client = MagicMock(spec=CourtListenerClient)
        main_module._client = sentinel_client

        @_decorated
        async def fn():
            raise NotFoundError("case not found")

        with pytest.raises(NotFoundError):
            await fn()

        # _client should still be the same object
        assert main_module._client is sentinel_client

    async def test_plain_tool_error_does_not_reset_client(self):
        """A vanilla ToolError (not an AuthenticationError) must not reset _client."""
        sentinel_client = MagicMock(spec=CourtListenerClient)
        main_module._client = sentinel_client

        @_decorated
        async def fn():
            raise ToolError("some user-visible error")

        with pytest.raises(ToolError):
            await fn()

        assert main_module._client is sentinel_client


# =============================================================================
# Concurrent client initialisation (audit fix 1)
# =============================================================================


class TestConcurrentClientInit:
    """
    Multiple concurrent calls to _get_client() must result in exactly ONE
    CourtListenerClient being constructed (the lock prevents double-init).
    """

    async def test_concurrent_client_init_creates_single_instance(self):
        """
        Three concurrent calls to _get_client() must each get the same instance
        and the CourtListenerClient constructor must be called exactly once.
        """
        # Ensure clean state (autouse fixture already runs but we reset explicitly)
        main_module._client = None
        main_module._client_lock = None

        construction_count = 0
        created_instance = None

        class TrackingClient:
            """Fake CourtListenerClient that counts constructions."""
            def __init__(self, token: str):
                nonlocal construction_count, created_instance
                construction_count += 1
                created_instance = self

        # Mock settings to supply a token
        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = "test_token_12345678901234567890"

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            with patch("courtlistener_mcp.main.CourtListenerClient", TrackingClient):
                results = await asyncio.gather(
                    main_module._get_client(),
                    main_module._get_client(),
                    main_module._get_client(),
                )

        # Only one construction should have occurred
        assert construction_count == 1

        # All three calls must have received the same instance
        assert results[0] is results[1]
        assert results[1] is results[2]
        assert results[0] is created_instance

    async def test_get_client_raises_tool_error_without_token(self):
        """
        When no token is available and no ctx is provided, _get_client must
        raise a ToolError with a helpful message.
        """
        main_module._client = None
        main_module._client_lock = None

        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = None

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            with pytest.raises(ToolError, match="COURTLISTENER_API_TOKEN"):
                await main_module._get_client(ctx=None)

    async def test_get_client_returns_existing_client(self):
        """
        If _client is already set, _get_client should return it without
        constructing a new one.
        """
        existing = MagicMock(spec=CourtListenerClient)
        main_module._client = existing

        mock_settings = MagicMock()
        mock_settings.get_api_token.return_value = "test_token_12345678901234567890"

        with patch("courtlistener_mcp.main._get_settings", return_value=mock_settings):
            result = await main_module._get_client()

        assert result is existing
