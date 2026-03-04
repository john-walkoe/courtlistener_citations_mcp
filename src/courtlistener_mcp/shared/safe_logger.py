"""Safe logging wrapper with automatic sanitization.

This module provides a logging wrapper that automatically sanitizes all log messages
using the LogSanitizer class to prevent sensitive data exposure and log injection attacks.

Security Features:
- Automatic sanitization of API tokens, passwords, credentials
- Log injection prevention (ANSI escapes, control characters)
- Consistent application of security controls across all logging statements

Usage:
    from courtlistener_mcp.shared.safe_logger import get_safe_logger

    logger = get_safe_logger(__name__)
    logger.error(f"API error: {exception_message}")  # Automatically sanitized
"""

import logging
from typing import Any

from .log_sanitizer import LogSanitizer


class SafeLogger:
    """Logger wrapper that automatically sanitizes all output.

    Ensures all log messages pass through LogSanitizer before being written,
    preventing sensitive data exposure.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.sanitizer = LogSanitizer()

    def _sanitize(self, message: Any) -> str:
        return self.sanitizer.sanitize_string(str(message))

    def debug(self, message: Any, *args, **kwargs):
        self.logger.debug(self._sanitize(message), *args, **kwargs)

    def info(self, message: Any, *args, **kwargs):
        self.logger.info(self._sanitize(message), *args, **kwargs)

    def warning(self, message: Any, *args, **kwargs):
        self.logger.warning(self._sanitize(message), *args, **kwargs)

    def error(self, message: Any, *args, **kwargs):
        self.logger.error(self._sanitize(message), *args, **kwargs)

    def critical(self, message: Any, *args, **kwargs):
        self.logger.critical(self._sanitize(message), *args, **kwargs)

    def exception(self, message: Any, *args, **kwargs):
        kwargs.setdefault('exc_info', True)
        self.logger.error(self._sanitize(message), *args, **kwargs)


def get_safe_logger(name: str) -> SafeLogger:
    """Get a safe logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        SafeLogger instance with automatic sanitization
    """
    return SafeLogger(logging.getLogger(name))
