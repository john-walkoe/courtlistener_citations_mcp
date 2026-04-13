"""
Targeted tests for failed audit findings:
- S02-4: Token format validation on elicitation
- S02-5: Elicitation error handling (warning not debug)
- G02-3: Name extraction exception logging
- G02-4: _citation_lookup_request auth/status handling
- G02-5: RuntimeError after retry exhaustion -> ToolError
- G02-6: InboundRateLimitMiddleware cleanup
- G02-7: Startup check for eyecite
"""
import asyncio
import time
import logging
import re
from collections import defaultdict
from unittest.mock import MagicMock, AsyncMock, patch
import httpx
import pytest

import courtlistener_mcp.main as main_module
from courtlistener_mcp.api.client import CourtListenerClient, DEFAULT_MAX_RETRIES


# =============================================================================
# S02-4: Token format validation on elicitation
# =============================================================================

class TestTokenFormatValidation:
    """FINDING-S02-4: Elicited token should be validated before storing."""

    def test_invalid_token_format_rejected(self):
        """Invalid token (not 40-char hex) should fail format validation."""
        invalid_tokens = [
            "too_short",
            "invalid_chars_not_hex",
            "a" * 39,   # too short
            "a" * 41,   # too long
            "",         # empty
            "gggggggggggggggggggggggggggggggggggggggggggg",  # 'g' not valid hex
        ]
        for token in invalid_tokens:
            assert re.fullmatch(r'[0-9a-f]{40}', token) is None, f"Token {token!r} should be rejected"

    def test_valid_token_format_accepted(self):
        """Valid 40-char hex token should pass validation."""
        valid_token = "a" * 40
        assert re.fullmatch(r'[0-9a-f]{40}', valid_token) is not None

    async def test_elicitation_stores_without_validation(self):
        """S02-4 FIXED: elicitation now validates token format (40-char hex)."""
        import inspect
        source = inspect.getsource(main_module._resolve_token)
        has_token_validation = "fullmatch" in source and "0-9a-f" in source
        assert has_token_validation, "S02-4: Token format validation should be present"


# =============================================================================
# S02-5: Elicitation error handling (warning not debug)
# =============================================================================

class TestElicitationErrorHandling:
    """FINDING-S02-5: Elicitation failures should log at WARNING, not DEBUG."""

    async def test_elicitation_exception_uses_debug_not_warning(self):
        """S02-5 FIXED: elicitation failures now log at WARNING level, not DEBUG."""
        import inspect
        source = inspect.getsource(main_module._resolve_token)
        lines = source.split('\n')
        in_elicitation_except = False
        for line in lines:
            if 'except Exception' in line and 'e:' in line:
                in_elicitation_except = True
            if in_elicitation_except and 'logger.warning' in line:
                assert True, "S02-5 fixed: logger.warning is used"
                return
            if in_elicitation_except and 'logger.debug' in line:
                assert False, "S02-5: logger.debug still used (should be warning)"
                return
        assert False, "S02-5: Could not find elicitation exception handler"


# =============================================================================
# G02-3: Name extraction exception logging
# =============================================================================

class TestNameExtractionLogging:
    """FINDING-G02-3: Silent exception in citation name extraction should log."""

    async def test_name_extraction_uses_bare_except_pass(self):
        """G02-3 FIXED: name extraction now logs non-ImportError exceptions."""
        import inspect
        from courtlistener_mcp import main
        source = inspect.getsource(main)

        # Look for the name extraction exception block
        has_warning_log = False
        in_name_extraction = False
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'name' in line.lower() and 'extraction' in line.lower():
                in_name_extraction = True
            if in_name_extraction and 'except Exception as e:' in line:
                # Check next few lines for warning log
                for j in range(i+1, min(i+5, len(lines))):
                    if 'logger.warning' in lines[j]:
                        has_warning_log = True
                        break
                break

        assert has_warning_log, "G02-3: Name extraction should log exceptions with logger.warning"


# =============================================================================
# G02-4: _citation_lookup_request auth/status handling
# =============================================================================

class TestCitationLookupRequestAuthHandling:
    """FINDING-G02-4: _citation_lookup_request should handle 401/403/404 like _request does."""

    async def test_citation_lookup_request_handles_401(self):
        """G02-4 FIXED: _citation_lookup_request now handles 401 with AuthenticationError."""
        import respx
        from courtlistener_mcp.errors import AuthenticationError
        from courtlistener_mcp.api.client import CourtListenerClient, API_BASE_URL

        token = "a" * 40
        client = CourtListenerClient(token=token)

        router = respx.MockRouter(assert_all_called=False)
        router.post(f"{API_BASE_URL}/citation-lookup/").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid token"})
        )

        client._client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={"Authorization": f"Token {token}"},
            transport=httpx.MockTransport(router.handler),
        )
        client._circuit_breaker.can_proceed = AsyncMock(return_value=True)
        client._rate_limiter.acquire = AsyncMock()

        with patch("courtlistener_mcp.api.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(AuthenticationError):
                await client._citation_lookup_request("test citation")


# =============================================================================
# G02-5: RuntimeError after retry exhaustion -> ToolError
# =============================================================================

class TestRetryExhaustion:
    """FINDING-G02-5: RuntimeError after all retries should be wrapped in ToolError."""

    async def test_runtime_error_escapes_decorator(self):
        """Current behavior: RuntimeError from exhausted retries escapes the decorator."""
        from fastmcp.exceptions import ToolError

        def _decorated(fn):
            return main_module._handle_client_errors(fn)

        @_decorated
        async def fn():
            raise RuntimeError(f"All {DEFAULT_MAX_RETRIES} retries exhausted for /test")

        result_type = None
        error_caught = None
        try:
            await fn()
        except ToolError as e:
            result_type = "ToolError"
            error_caught = e
        except RuntimeError as e:
            result_type = "RuntimeError"
            error_caught = e
        except Exception as e:
            result_type = type(e).__name__
            error_caught = e

        # Current behavior: RuntimeError escapes
        assert result_type == "RuntimeError", f"G02-5: Expected RuntimeError, got {result_type}"


# =============================================================================
# G02-6: InboundRateLimitMiddleware cleanup
# =============================================================================

class TestRateLimitMiddlewareCleanup:
    """FINDING-G02-6: Cleanup interval should be parameterized, not hardcoded."""

    def test_cleanup_removes_expired_entries(self):
        """G02-6 FIXED: rate limiter removes expired IPs via inline cleanup."""
        from courtlistener_mcp.shared.http_rate_limit import InboundRateLimitMiddleware

        app_mock = AsyncMock()
        middleware = InboundRateLimitMiddleware(app=app_mock, window_seconds=60)

        now = time.monotonic()
        # Add an IP with an expired entry — should be pruned on next call
        middleware.requests["1.1.1.1"] = [now - 120]

        # Manually force the cleanup condition by patching _last_cleanup
        middleware._last_cleanup = now - 61

        async def run_call():
            # A call from a different IP that has a live entry (so app is called)
            scope = {"type": "http", "client": ("2.2.2.2", 0), "path": "/mcp", "method": "POST"}
            receive = AsyncMock()
            send = AsyncMock()
            # Use the current patched time for the live entry so it survives
            current = time.monotonic()
            middleware.requests["2.2.2.2"] = [current]
            await middleware(scope, receive, send)

        with patch('time.monotonic', return_value=now + 61):
            asyncio.run(run_call())

        # 1.1.1.1 should be dropped (all timestamps expired)
        assert "1.1.1.1" not in middleware.requests
        # 2.2.2.2 should be kept (has a live timestamp at the patched time)
        assert "2.2.2.2" in middleware.requests

    def test_cleanup_interval_hardcoded(self):
        """G02-6 FIXED: cleanup interval is now parameterized by window_seconds."""
        import inspect
        from courtlistener_mcp.shared.http_rate_limit import InboundRateLimitMiddleware
        source = inspect.getsource(InboundRateLimitMiddleware)

        # Check that cleanup interval uses window_seconds / self._cleanup_interval
        # instead of hardcoded 60
        uses_hardcoded_60 = False
        lines = source.split('\n')
        for line in lines:
            if '60' in line and 'cleanup' in line.lower():
                uses_hardcoded_60 = True
                break

        assert not uses_hardcoded_60, "G02-6: Cleanup interval should be parameterized, not hardcoded to 60"


# =============================================================================
# G02-7: Startup check for eyecite
# =============================================================================

class TestEyeciteGracefulDegradation:
    """FINDING-G02-7: Server should warn at startup if eyecite is not installed."""

    def test_no_startup_eyecite_check(self):
        """Current behavior: no startup check for eyecite availability."""
        import inspect
        from courtlistener_mcp.main import run_server

        source = inspect.getsource(run_server)
        has_eyecite_check = ("eyecite" in source.lower() and "warning" in source.lower()) or \
                            ("get_citations" in source and "import" in source and "warning" in source)

        assert not has_eyecite_check, "G02-7: Startup check for eyecite is missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])