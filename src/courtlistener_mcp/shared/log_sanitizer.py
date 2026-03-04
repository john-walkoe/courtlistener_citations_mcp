"""
Log Sanitization Module for Security

Provides sanitization functions to prevent log injection attacks and protect
sensitive data from being exposed in log outputs.

Security Features:
- Automatic masking of CourtListener API tokens, generic API keys, JWT tokens
- Log injection prevention (ANSI escapes, control characters)
- IP address and email partial masking
- HTTP header sanitization
"""

import html
import json
import re
from typing import Any, Dict


class LogSanitizer:
    """Sanitizer for log injection protection and sensitive data filtering."""

    # Sensitive HTTP header keys to remove
    SENSITIVE_HEADER_KEYS = [
        "X-API-KEY", "x-api-key",
        "Authorization", "authorization",
        "API-KEY", "api-key",
        "Bearer", "bearer",
        "Token", "token",
        "X-Auth-Token", "x-auth-token",
    ]

    # Patterns for detecting and masking sensitive data
    # Order matters: more specific patterns first, generic patterns last
    SENSITIVE_PATTERNS = [
        # CourtListener "Token <hex>" authorization header (most specific)
        (r'(Token\s+)([0-9a-fA-F]{20,})', r'\1[CL_API_TOKEN]'),

        # CourtListener API tokens - bare 40-char hex strings
        (r'\b([0-9a-f]{40})\b', r'[CL_API_TOKEN]'),

        # Generic API keys with prefixes (sk_live_, pk_test_, etc.)
        (r'(?:sk|pk)_(?:live|test)_[a-zA-Z0-9]{10,}', r'[API_KEY]'),
        (r'(?:sk|pk|live|test)_[a-zA-Z0-9]{10,}', r'[API_KEY]'),

        # Bearer tokens
        (r'(bearer\s+)([a-zA-Z0-9._-]{20,})', r'\1[TOKEN]'),

        # API keys and tokens in structured format (key=value, key: value)
        (r'(api[_-]?key["\s:=]+)([a-zA-Z0-9]{20,})', r'\1[API_KEY]'),
        (r'(token["\s:=]+)([a-zA-Z0-9]{20,})', r'\1[TOKEN]'),

        # Passwords and credentials
        (r'(password["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),
        (r'(pwd["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),
        (r'(secret["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),

        # Email addresses (partial masking)
        (r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1[...]@\2'),

        # IP addresses (partial masking for privacy)
        (r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})', r'\1.\2.[XXX].[XXX]'),
    ]

    # Control characters to remove (except common ones like \n, \t)
    CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')

    # Log injection patterns to neutralize
    LOG_INJECTION_PATTERNS = [
        r'[\r\n]',
        r'\t',
        r'\x1b\[[0-9;]*[a-zA-Z]',
        r'\x1b[()[\]#;?]*[0-9]*[a-zA-Z@]',
    ]

    @classmethod
    def sanitize_for_json(cls, obj: Any) -> Any:
        """Recursively sanitize data for safe JSON logging."""
        if isinstance(obj, dict):
            return {key: cls.sanitize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [cls.sanitize_for_json(item) for item in obj]
        elif isinstance(obj, str):
            return cls.sanitize_string(obj)
        elif obj is None:
            return obj
        else:
            return cls.sanitize_string(str(obj))

    @classmethod
    def sanitize_string(cls, text: str, max_length: int = 1000) -> str:
        """Sanitize a string for safe logging.

        Args:
            text: String to sanitize
            max_length: Maximum length for output (prevents log flooding)

        Returns:
            Sanitized string safe for logging
        """
        if not isinstance(text, str):
            text = str(text)

        if len(text) > max_length:
            text = text[:max_length] + "...[TRUNCATED]"

        text = cls.CONTROL_CHAR_PATTERN.sub('', text)

        for pattern in cls.LOG_INJECTION_PATTERNS:
            text = re.sub(pattern, '[FILTERED]', text)

        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        text = html.escape(text, quote=False)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def sanitize_headers(cls, headers: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive headers from HTTP headers dictionary."""
        sanitized = headers.copy()
        for key in cls.SENSITIVE_HEADER_KEYS:
            sanitized.pop(key, None)
        return sanitized

    @classmethod
    def create_safe_log_entry(cls, message: str, **kwargs) -> Dict[str, Any]:
        """Create a safe log entry with sanitized data."""
        return {
            "message": cls.sanitize_string(message),
            **cls.sanitize_for_json(kwargs),
        }

    @classmethod
    def validate_json_safe(cls, obj: Any) -> bool:
        """Validate that an object is safe for JSON serialization."""
        try:
            json.dumps(obj)
            return True
        except (TypeError, ValueError, OverflowError):
            return False
