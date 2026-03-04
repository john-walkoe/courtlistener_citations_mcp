"""
Unified Secure Storage for CourtListener API Token

Priority chain:
1. Windows Credential Manager (via keyring library) - PRIMARY
2. File-based DPAPI (~/.courtlistener_api_token) - FALLBACK
3. Environment variable (COURTLISTENER_API_TOKEN) - handled by settings.py

Automatically migrates from file-based DPAPI to Credential Manager on first access.
Graceful fallback if keyring backend unavailable.
"""

import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from ..config.api_constants import (
    DPAPI_DESCRIPTION,
    DPAPI_ENTROPY_BYTES,
    SECURE_STORAGE_FILENAME,
)
from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

_STORAGE_PATH = Path.home() / SECURE_STORAGE_FILENAME
_KEYRING_SERVICE = "CourtListener MCP"
_KEYRING_USERNAME = "API_TOKEN"


# ============================================================================
# Keyring (Windows Credential Manager) Operations - PRIMARY
# ============================================================================

def _get_token_from_keyring() -> Optional[str]:
    """
    Retrieve API token from Windows Credential Manager via keyring.

    Returns:
        Token string if found, None otherwise.
    """
    try:
        import keyring
        token = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if token:
            logger.debug("Successfully retrieved API token from Credential Manager")
        return token
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug(f"Keyring unavailable or no token stored: {e}")
        return None


def _store_token_in_keyring(token: str) -> bool:
    """
    Store API token in Windows Credential Manager via keyring.

    Args:
        token: The API token to store

    Returns:
        True if stored successfully, False otherwise.
    """
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, token)
        logger.info("API token stored in Windows Credential Manager")
        return True
    except (ImportError, OSError, RuntimeError) as e:
        logger.warning(f"Failed to store token in keyring: {e}")
        return False


def _delete_token_from_keyring() -> bool:
    """Delete API token from Windows Credential Manager."""
    try:
        import keyring
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        logger.info("Token deleted from Windows Credential Manager")
        return True
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug(f"No token in keyring or deletion failed: {e}")
        return False


# ============================================================================
# File-based DPAPI Operations - FALLBACK
# ============================================================================

def _restrict_file_permissions(path: Path) -> None:
    """Restrict file to current user only (Windows ACL or POSIX chmod)."""
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    try:
        username = os.environ.get("USERNAME", "")
        if username:
            import subprocess
            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", f"{username}:(R,W)"],
                capture_output=True, check=True, timeout=10,
            )
    except (subprocess.SubprocessError, OSError):
        pass  # Best-effort; DPAPI still protects decryption


def _get_token_from_file() -> Optional[str]:
    """
    Retrieve API token from file-based DPAPI storage (legacy fallback).

    Returns:
        Decrypted API token string, or None if not stored or unavailable.
    """
    if sys.platform != "win32":
        logger.debug("DPAPI not available on this platform")
        return None

    if not _STORAGE_PATH.exists():
        logger.debug(f"File-based storage not found: {_STORAGE_PATH}")
        return None

    try:
        raw_data = _STORAGE_PATH.read_bytes()

        if len(raw_data) <= DPAPI_ENTROPY_BYTES:
            logger.warning("Storage file is too small (corrupt?)")
            return None

        entropy = raw_data[:DPAPI_ENTROPY_BYTES]
        encrypted_data = raw_data[DPAPI_ENTROPY_BYTES:]

        from .dpapi_crypto import decrypt_with_dpapi
        decrypted = decrypt_with_dpapi(encrypted_data, entropy)
        token = decrypted.decode("utf-8").strip()

        if not token:
            logger.warning("Decrypted token is empty")
            return None

        logger.debug("Retrieved API token from file-based DPAPI storage")
        return token

    except (OSError, UnicodeDecodeError, ImportError) as e:
        logger.warning(f"Failed to read file-based storage: {e}")
        return None


def _migrate_file_to_keyring() -> None:
    """Migrate token from file-based DPAPI to Credential Manager."""
    try:
        file_token = _get_token_from_file()
        if file_token and _store_token_in_keyring(file_token):
            logger.info("Migrated token from file-based DPAPI to Credential Manager")
            # Keep file as backup during migration (don't delete yet)
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug(f"Migration failed (non-critical): {e}")


def get_api_token() -> Optional[str]:
    """
    Retrieve CourtListener API token from secure storage.

    Priority:
    1. Windows Credential Manager (via keyring)
    2. File-based DPAPI (legacy fallback)

    Automatically migrates from file-based to keyring on first successful retrieval.

    Returns:
        API token string, or None if not stored or unavailable.
    """
    # Try Credential Manager first (primary)
    token = _get_token_from_keyring()
    if token:
        return token

    # Fall back to file-based DPAPI (legacy)
    token = _get_token_from_file()
    if token:
        # Attempt migration to keyring for next time
        _migrate_file_to_keyring()
        return token

    logger.debug("No API token found in any secure storage")
    return None


def _store_token_in_file(token: str) -> bool:
    """
    Store API token using file-based DPAPI encryption (legacy fallback).

    Args:
        token: The API token to store

    Returns:
        True if stored successfully, False otherwise.
    """
    if sys.platform != "win32":
        logger.warning("DPAPI not available on this platform")
        return False

    try:
        entropy = secrets.token_bytes(DPAPI_ENTROPY_BYTES)

        from .dpapi_crypto import encrypt_with_dpapi
        encrypted = encrypt_with_dpapi(
            token.strip().encode("utf-8"),
            entropy,
            DPAPI_DESCRIPTION
        )

        _STORAGE_PATH.write_bytes(entropy + encrypted)
        _restrict_file_permissions(_STORAGE_PATH)

        logger.info(f"API token stored in file-based DPAPI at {_STORAGE_PATH}")
        return True

    except (OSError, ImportError) as e:
        logger.error(f"Failed to store token in file: {e}")
        return False


def store_api_token(token: str) -> bool:
    """
    Store CourtListener API token in secure storage.

    Priority:
    1. Windows Credential Manager (via keyring) - PRIMARY
    2. File-based DPAPI - FALLBACK

    Args:
        token: The API token to store

    Returns:
        True if stored successfully (either method), False if both failed.
    """
    if not token or not token.strip():
        logger.error("Cannot store empty token")
        return False

    token = token.strip()

    # Try Credential Manager first (primary)
    if _store_token_in_keyring(token):
        # Also store in file as backup (redundancy is good for important data)
        _store_token_in_file(token)
        return True

    # Fall back to file-based DPAPI only
    if _store_token_in_file(token):
        logger.warning("Stored in file-based DPAPI only (keyring unavailable)")
        return True

    # Both methods failed
    logger.error("Failed to store API token in any secure storage")
    return False


def has_stored_token() -> bool:
    """
    Check if a token is stored in any secure storage location.

    Returns:
        True if token exists in keyring OR file-based storage.
    """
    # Check keyring first
    if _get_token_from_keyring():
        return True

    # Check file-based storage
    if sys.platform == "win32":
        return _STORAGE_PATH.exists() and _STORAGE_PATH.stat().st_size > DPAPI_ENTROPY_BYTES

    return False


def delete_stored_token() -> bool:
    """
    Delete the stored API token from ALL storage locations.

    Returns:
        True if any token was deleted, False if no token was found.
    """
    deleted_any = False

    # Delete from keyring
    if _delete_token_from_keyring():
        deleted_any = True

    # Delete from file-based storage
    try:
        if _STORAGE_PATH.exists():
            _STORAGE_PATH.unlink()
            logger.info("Deleted token from file-based DPAPI storage")
            deleted_any = True
    except OSError as e:
        logger.error(f"Failed to delete file-based token: {e}")

    if deleted_any:
        logger.info("API token(s) deleted from all secure storage locations")
    else:
        logger.debug("No stored token found to delete")

    return deleted_any
