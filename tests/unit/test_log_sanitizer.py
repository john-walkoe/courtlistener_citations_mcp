"""
Unit tests for courtlistener_mcp.shared.log_sanitizer.LogSanitizer.

Covers:
- Token masking (CourtListener API token patterns)
- Control-character stripping
- ANSI escape filtering
- Log injection prevention (newline / carriage return)
- String truncation
- HTTP header sanitization
- Recursive JSON sanitization
- Negative assertion: token never leaks through sanitized output
"""

import pytest

from courtlistener_mcp.shared.log_sanitizer import LogSanitizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A realistic-looking 40-char lowercase hex token (same format CourtListener uses)
_REAL_TOKEN = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
_TOKEN_HEADER_VALUE = f"Token {_REAL_TOKEN}"


# =============================================================================
# Token masking
# =============================================================================


class TestTokenMasking:
    """CourtListener API token patterns must be redacted."""

    def test_masks_courtlistener_api_token(self):
        """'Token <40-hex>' authorization header value should be masked."""
        result = LogSanitizer.sanitize_string(_TOKEN_HEADER_VALUE)
        assert "[CL_API_TOKEN]" in result
        assert _REAL_TOKEN not in result

    def test_masks_bare_40char_hex_token(self):
        """A bare 40-char lowercase hex string should be replaced with [CL_API_TOKEN]."""
        text = f"Retrieved token: {_REAL_TOKEN}"
        result = LogSanitizer.sanitize_string(text)
        assert "[CL_API_TOKEN]" in result
        assert _REAL_TOKEN not in result

    def test_token_not_in_sanitized_output(self):
        """The raw token must never appear in the sanitized output."""
        text = f"Authorization: Token {_REAL_TOKEN} - request succeeded"
        result = LogSanitizer.sanitize_string(text)
        assert _REAL_TOKEN not in result


# =============================================================================
# Control characters
# =============================================================================


class TestControlCharacters:
    """Non-printable control characters should be stripped."""

    def test_strips_null_byte(self):
        result = LogSanitizer.sanitize_string("before\x00after")
        assert "\x00" not in result

    def test_strips_soh_control_char(self):
        result = LogSanitizer.sanitize_string("before\x01after")
        assert "\x01" not in result

    def test_strips_bel_control_char(self):
        result = LogSanitizer.sanitize_string("before\x07after")
        assert "\x07" not in result

    def test_strips_multiple_control_characters(self):
        text = "a\x00b\x01c\x07d"
        result = LogSanitizer.sanitize_string(text)
        for char in ["\x00", "\x01", "\x07"]:
            assert char not in result


# =============================================================================
# ANSI escape sequences
# =============================================================================


class TestAnsiEscapeSequences:
    """ANSI terminal escape codes are a log injection vector and must be neutralised."""

    def test_filters_ansi_escape_sequences(self):
        """'\x1b[31mRed\x1b[0m' should have ANSI codes replaced."""
        text = "\x1b[31mRed\x1b[0m"
        result = LogSanitizer.sanitize_string(text)
        assert "\x1b" not in result

    def test_filters_removes_escape_byte_from_ansi_sequence(self):
        """
        The ESC byte (\x1b) is stripped by the control-character pattern.
        After stripping, the remaining bracket sequences may still be present
        but the dangerous ESC prefix that makes them terminal directives is gone.
        Either way, the raw ESC byte must not appear in the output.
        """
        text = "\x1b[31mcolored\x1b[0m"
        result = LogSanitizer.sanitize_string(text)
        # The ESC control byte is stripped — the terminal sequence is neutralised
        assert "\x1b" not in result
        # The visible word 'colored' should still be present
        assert "colored" in result


# =============================================================================
# Log injection prevention
# =============================================================================


class TestLogInjectionPrevention:
    """Newlines and carriage returns are classic log injection vectors."""

    def test_prevents_newline_injection(self):
        """Embedded newlines should be replaced with [FILTERED]."""
        text = "line1\nline2"
        result = LogSanitizer.sanitize_string(text)
        assert "\n" not in result
        assert "[FILTERED]" in result

    def test_prevents_carriage_return_injection(self):
        """Embedded carriage returns should be replaced with [FILTERED]."""
        text = "line1\rline2"
        result = LogSanitizer.sanitize_string(text)
        assert "\r" not in result
        assert "[FILTERED]" in result

    def test_prevents_crlf_injection(self):
        """CRLF combination should be fully neutralised."""
        text = "before\r\nafter"
        result = LogSanitizer.sanitize_string(text)
        assert "\r" not in result
        assert "\n" not in result


# =============================================================================
# String truncation
# =============================================================================


class TestStringTruncation:
    """Strings longer than max_length should be truncated with a marker."""

    def test_truncates_long_strings(self):
        """A 1001-char string should be truncated and end with '[TRUNCATED]'."""
        long_string = "x" * 1001
        result = LogSanitizer.sanitize_string(long_string)
        assert "[TRUNCATED]" in result

    def test_does_not_truncate_short_strings(self):
        """A string within the default max_length should not be truncated."""
        short = "hello world"
        result = LogSanitizer.sanitize_string(short)
        assert "[TRUNCATED]" not in result

    def test_truncation_respects_custom_max_length(self):
        """A custom max_length should be honoured."""
        text = "a" * 50
        result = LogSanitizer.sanitize_string(text, max_length=20)
        assert "[TRUNCATED]" in result


# =============================================================================
# Header sanitization
# =============================================================================


class TestSanitizeHeaders:
    """Sensitive HTTP headers must be removed; safe headers must be preserved."""

    def test_sanitize_headers_removes_authorization(self):
        """Authorization header should be removed."""
        headers = {"Authorization": f"Token {_REAL_TOKEN}", "Content-Type": "application/json"}
        result = LogSanitizer.sanitize_headers(headers)
        assert "Authorization" not in result
        assert result["Content-Type"] == "application/json"

    def test_sanitize_headers_removes_api_key(self):
        """x-api-key header should be removed."""
        headers = {"x-api-key": "secret", "Accept": "application/json"}
        result = LogSanitizer.sanitize_headers(headers)
        assert "x-api-key" not in result
        assert result["Accept"] == "application/json"

    def test_sanitize_headers_does_not_modify_original(self):
        """sanitize_headers must not mutate the original dict."""
        original = {"Authorization": "Token secret", "Accept": "*/*"}
        original_copy = original.copy()
        LogSanitizer.sanitize_headers(original)
        assert original == original_copy

    def test_sanitize_headers_preserves_safe_headers(self):
        """Non-sensitive headers should pass through unchanged."""
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Test/1.0"}
        result = LogSanitizer.sanitize_headers(headers)
        assert result == headers


# =============================================================================
# JSON / recursive sanitization
# =============================================================================


class TestSanitizeForJson:
    """sanitize_for_json should recursively sanitize nested structures."""

    def test_sanitize_for_json_handles_dict(self):
        """A dict containing a token value should have the token sanitized."""
        data = {"token": _REAL_TOKEN, "status": "ok"}
        result = LogSanitizer.sanitize_for_json(data)
        assert isinstance(result, dict)
        assert _REAL_TOKEN not in str(result)

    def test_sanitize_for_json_handles_list(self):
        """A list containing a token string should have it sanitized."""
        data = [_TOKEN_HEADER_VALUE, "other value"]
        result = LogSanitizer.sanitize_for_json(data)
        assert isinstance(result, list)
        assert _REAL_TOKEN not in str(result)

    def test_sanitize_for_json_handles_nested_dict(self):
        """Nested dicts should be sanitized recursively."""
        data = {"outer": {"inner": _REAL_TOKEN}}
        result = LogSanitizer.sanitize_for_json(data)
        assert _REAL_TOKEN not in str(result)

    def test_sanitize_for_json_handles_none_values(self):
        """None values should pass through without error."""
        data = {"key": None}
        result = LogSanitizer.sanitize_for_json(data)
        assert result["key"] is None

    def test_sanitize_for_json_handles_numeric_values(self):
        """Numeric values should be converted and sanitized without crashing."""
        data = {"count": 42, "pi": 3.14}
        result = LogSanitizer.sanitize_for_json(data)
        assert isinstance(result, dict)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions for LogSanitizer."""

    def test_safe_empty_string(self):
        """Empty string input should return empty string (or whitespace stripped empty)."""
        result = LogSanitizer.sanitize_string("")
        assert result == ""

    def test_sanitize_string_accepts_non_string_input(self):
        """Non-string inputs (e.g., integers) should be converted without error."""
        result = LogSanitizer.sanitize_string(12345)
        assert isinstance(result, str)

    def test_sanitize_string_with_unicode_safe_content(self):
        """Regular Unicode text should pass through without corruption."""
        text = "Café legal brief analysis."
        result = LogSanitizer.sanitize_string(text)
        assert "legal brief" in result
