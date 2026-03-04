"""Centralized error types for CourtListener MCP."""

from fastmcp.exceptions import ToolError


class CourtListenerError(ToolError):
    """Base error for all CourtListener MCP errors."""
    pass


class AuthenticationError(CourtListenerError):
    """API token is missing, invalid, or expired (HTTP 401/403)."""
    pass


class ValidationError(CourtListenerError):
    """Invalid input parameters."""
    pass


class RateLimitError(CourtListenerError):
    """Rate limit exceeded after all retries (HTTP 429)."""
    pass


class NotFoundError(CourtListenerError):
    """Requested resource not found (HTTP 404)."""
    pass


class UpstreamError(CourtListenerError):
    """CourtListener API error (HTTP 5xx or unexpected status)."""
    pass
