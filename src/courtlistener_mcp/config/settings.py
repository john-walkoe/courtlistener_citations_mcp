"""
Application Settings

Pydantic BaseSettings with environment variable support and DPAPI fallback.
Priority chain: env var -> DPAPI secure storage -> elicitation prompt (at tool call time)
"""

import os
from typing import Optional

from pydantic_settings import BaseSettings

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class Settings(BaseSettings):
    """Application configuration with env var and DPAPI fallback."""

    courtlistener_api_token: Optional[str] = None
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.courtlistener_api_token:
            self._load_from_secure_storage()

    def _load_from_secure_storage(self) -> None:
        """Attempt to load API token from DPAPI secure storage."""
        try:
            from ..shared.secure_storage import get_api_token
            token = get_api_token()
            if token:
                self.courtlistener_api_token = token
                logger.debug("Loaded API token from secure storage")
        except (ImportError, OSError, RuntimeError) as e:
            logger.debug(f"Secure storage unavailable: {e}")

    def get_api_token(self) -> Optional[str]:
        """Get API token from any available source."""
        if self.courtlistener_api_token:
            return self.courtlistener_api_token

        env_token = os.getenv("COURTLISTENER_API_TOKEN")
        if env_token:
            self.courtlistener_api_token = env_token
            return env_token

        try:
            from ..shared.secure_storage import get_api_token
            token = get_api_token()
            if token:
                self.courtlistener_api_token = token
                return token
        except (ImportError, OSError, RuntimeError):
            pass

        return None


def get_settings() -> Settings:
    """Create and return application settings."""
    return Settings()
