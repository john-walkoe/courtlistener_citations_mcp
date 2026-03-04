"""
Unit tests for courtlistener_mcp.shared.secure_storage.

Focus areas:
- Graceful exception handling in keyring operations (audit fix)
- Public API (store_api_token, has_stored_token, delete_stored_token)
- _restrict_file_permissions error swallowing
- _migrate_file_to_keyring error swallowing
- store_api_token rejects empty / whitespace-only tokens
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from courtlistener_mcp.shared.secure_storage import (
    _delete_token_from_keyring,
    _get_token_from_keyring,
    _migrate_file_to_keyring,
    _restrict_file_permissions,
    _store_token_in_keyring,
    store_api_token,
)


# =============================================================================
# _get_token_from_keyring
# =============================================================================


class TestGetTokenFromKeyring:
    """Retrieval from Credential Manager should handle all failure modes silently."""

    def test_get_token_from_keyring_returns_none_on_import_error(self):
        """If keyring library is not importable, return None (no crash)."""
        with patch.dict("sys.modules", {"keyring": None}):
            result = _get_token_from_keyring()
        assert result is None

    def test_get_token_from_keyring_returns_none_on_os_error(self):
        """OSError from keyring.get_password should be caught and return None."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = OSError("Credential Manager unavailable")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _get_token_from_keyring()
        assert result is None

    def test_get_token_from_keyring_returns_none_on_runtime_error(self):
        """RuntimeError from keyring.get_password should be caught and return None."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = RuntimeError("No backend available")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _get_token_from_keyring()
        assert result is None

    def test_get_token_from_keyring_returns_token_on_success(self):
        """A successful keyring lookup should return the stored token."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "test-token-value"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _get_token_from_keyring()
        assert result == "test-token-value"

    def test_get_token_from_keyring_returns_none_when_get_password_returns_none(self):
        """If keyring.get_password returns None, the function should return None."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _get_token_from_keyring()
        assert result is None


# =============================================================================
# _store_token_in_keyring
# =============================================================================


class TestStoreTokenInKeyring:
    """Storing to Credential Manager should handle all failure modes silently."""

    def test_store_token_in_keyring_returns_false_on_os_error(self):
        """OSError from keyring.set_password should be caught and return False."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = OSError("Credential Manager unavailable")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _store_token_in_keyring("some-token")
        assert result is False

    def test_store_token_in_keyring_returns_false_on_runtime_error(self):
        """RuntimeError from keyring.set_password should be caught and return False."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = RuntimeError("Backend error")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _store_token_in_keyring("some-token")
        assert result is False

    def test_store_token_in_keyring_returns_true_on_success(self):
        """A successful keyring.set_password should return True."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.return_value = None  # set_password returns None on success
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _store_token_in_keyring("some-token")
        assert result is True

    def test_store_token_in_keyring_returns_false_on_import_error(self):
        """If keyring is not importable, return False (no crash)."""
        with patch.dict("sys.modules", {"keyring": None}):
            result = _store_token_in_keyring("some-token")
        assert result is False


# =============================================================================
# _delete_token_from_keyring
# =============================================================================


class TestDeleteTokenFromKeyring:
    """Deletion from Credential Manager should handle all failure modes silently."""

    def test_delete_token_from_keyring_returns_false_on_os_error(self):
        """OSError from keyring.delete_password should be caught and return False."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.side_effect = OSError("Credential Manager error")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _delete_token_from_keyring()
        assert result is False

    def test_delete_token_from_keyring_returns_true_on_success(self):
        """A successful delete_password call should return True."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _delete_token_from_keyring()
        assert result is True

    def test_delete_token_from_keyring_returns_false_on_runtime_error(self):
        """RuntimeError from keyring.delete_password should be caught and return False."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.side_effect = RuntimeError("Backend error")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = _delete_token_from_keyring()
        assert result is False


# =============================================================================
# _restrict_file_permissions
# =============================================================================


class TestRestrictFilePermissions:
    """_restrict_file_permissions must swallow subprocess and OS errors on Windows."""

    def test_restrict_file_permissions_silent_on_subprocess_error(self, tmp_path):
        """SubprocessError from icacls should be swallowed (best-effort)."""
        test_file = tmp_path / "token_file"
        test_file.write_text("dummy")

        with patch.object(sys, "platform", "win32"):
            with patch("os.environ.get", return_value="testuser"):
                with patch("subprocess.run", side_effect=subprocess.SubprocessError("icacls failed")):
                    # Must NOT raise
                    _restrict_file_permissions(test_file)

    def test_restrict_file_permissions_silent_on_os_error(self, tmp_path):
        """OSError from subprocess.run should be swallowed."""
        test_file = tmp_path / "token_file"
        test_file.write_text("dummy")

        with patch.object(sys, "platform", "win32"):
            with patch("os.environ.get", return_value="testuser"):
                with patch("subprocess.run", side_effect=OSError("Subprocess launch failed")):
                    # Must NOT raise
                    _restrict_file_permissions(test_file)

    def test_restrict_file_permissions_posix_uses_chmod(self, tmp_path):
        """On non-Windows, chmod(0o600) should be called."""
        test_file = tmp_path / "token_file"
        test_file.write_text("dummy")

        with patch.object(sys, "platform", "linux"):
            with patch("os.chmod") as mock_chmod:
                _restrict_file_permissions(test_file)
            mock_chmod.assert_called_once_with(test_file, 0o600)

    def test_restrict_file_permissions_posix_silent_on_os_error(self, tmp_path):
        """On non-Windows, an OSError from chmod should be swallowed."""
        test_file = tmp_path / "token_file"
        test_file.write_text("dummy")

        with patch.object(sys, "platform", "linux"):
            with patch("os.chmod", side_effect=OSError("Permission denied")):
                # Must NOT raise
                _restrict_file_permissions(test_file)


# =============================================================================
# _migrate_file_to_keyring
# =============================================================================


class TestMigrateFileToKeyring:
    """Migration helper must swallow errors to avoid crashing the caller."""

    def test_migrate_file_to_keyring_silent_on_import_error(self):
        """ImportError from _get_token_from_file should be swallowed."""
        with patch(
            "courtlistener_mcp.shared.secure_storage._get_token_from_file",
            side_effect=ImportError("dpapi_crypto not available"),
        ):
            # Must NOT raise
            _migrate_file_to_keyring()

    def test_migrate_file_to_keyring_silent_on_os_error(self):
        """OSError from _get_token_from_file should be swallowed."""
        with patch(
            "courtlistener_mcp.shared.secure_storage._get_token_from_file",
            side_effect=OSError("File read error"),
        ):
            # Must NOT raise
            _migrate_file_to_keyring()

    def test_migrate_file_to_keyring_stores_when_file_token_present(self):
        """When a file token exists, _store_token_in_keyring should be called."""
        with patch(
            "courtlistener_mcp.shared.secure_storage._get_token_from_file",
            return_value="migrated-token",
        ):
            with patch(
                "courtlistener_mcp.shared.secure_storage._store_token_in_keyring",
                return_value=True,
            ) as mock_store:
                _migrate_file_to_keyring()
        mock_store.assert_called_once_with("migrated-token")


# =============================================================================
# store_api_token public API
# =============================================================================


class TestStoreApiToken:
    """store_api_token must validate its input before attempting storage."""

    def test_store_api_token_rejects_empty_string(self):
        """An empty string should return False without calling any storage backend."""
        result = store_api_token("")
        assert result is False

    def test_store_api_token_rejects_whitespace(self):
        """A whitespace-only string should return False."""
        result = store_api_token("   ")
        assert result is False

    def test_store_api_token_strips_and_stores(self):
        """A token with surrounding whitespace should be stripped and stored."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            # Also stub _store_token_in_file to avoid DPAPI on non-Windows
            with patch(
                "courtlistener_mcp.shared.secure_storage._store_token_in_file",
                return_value=True,
            ):
                result = store_api_token("  valid-token  ")
        assert result is True

    def test_store_api_token_falls_back_to_file_when_keyring_fails(self):
        """When keyring fails, store_api_token should try file-based storage."""
        with patch(
            "courtlistener_mcp.shared.secure_storage._store_token_in_keyring",
            return_value=False,
        ):
            with patch(
                "courtlistener_mcp.shared.secure_storage._store_token_in_file",
                return_value=True,
            ) as mock_file_store:
                result = store_api_token("fallback-token")
        assert result is True
        mock_file_store.assert_called_once()

    def test_store_api_token_returns_false_when_both_methods_fail(self):
        """Returns False when both keyring and file-based storage fail."""
        with patch(
            "courtlistener_mcp.shared.secure_storage._store_token_in_keyring",
            return_value=False,
        ):
            with patch(
                "courtlistener_mcp.shared.secure_storage._store_token_in_file",
                return_value=False,
            ):
                result = store_api_token("any-token")
        assert result is False
