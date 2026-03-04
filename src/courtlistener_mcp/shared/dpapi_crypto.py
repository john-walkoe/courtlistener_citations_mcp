"""
Windows DPAPI Cryptographic Operations

Centralized DPAPI encryption/decryption functionality.
CWE-330 compliant: Uses secrets.token_bytes(32) for entropy.

Security Features:
- DPAPI encryption: Per-user, per-machine encryption on Windows
- Cryptographically secure entropy generation
- Proper memory cleanup with LocalFree
"""

import ctypes
import ctypes.wintypes
import sys
from typing import Optional


class DATA_BLOB(ctypes.Structure):
    """Windows DATA_BLOB structure for DPAPI operations."""
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char))
    ]


def extract_data_from_blob(blob: DATA_BLOB) -> bytes:
    """Extract bytes from a DATA_BLOB structure and free memory."""
    if not blob.cbData:
        return b''

    cbData = int(blob.cbData)
    pbData = blob.pbData
    buffer = ctypes.create_string_buffer(cbData)
    ctypes.memmove(buffer, pbData, cbData)

    ctypes.windll.kernel32.LocalFree(pbData)

    return buffer.raw


def encrypt_with_dpapi(
    data: bytes,
    entropy: bytes,
    description: str = "CourtListener MCP API Token"
) -> bytes:
    """
    Encrypt data using Windows DPAPI with custom entropy.

    Args:
        data: The data to encrypt
        entropy: Custom entropy for additional security (recommend 32 bytes)
        description: Description for the encrypted data

    Returns:
        Encrypted data as bytes

    Raises:
        OSError: If encryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(
        ctypes.create_string_buffer(data),
        ctypes.POINTER(ctypes.c_char)
    )
    data_in.cbData = len(data)

    data_out = DATA_BLOB()

    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(entropy),
        ctypes.POINTER(ctypes.c_char)
    )
    entropy_blob.cbData = len(entropy)

    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),
        description,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out)
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptProtectData failed with error code: {error_code}")

    return extract_data_from_blob(data_out)


def decrypt_with_dpapi(encrypted_data: bytes, entropy: bytes) -> bytes:
    """
    Decrypt data using Windows DPAPI with custom entropy.

    Args:
        encrypted_data: The encrypted data to decrypt
        entropy: Custom entropy used during encryption (must match)

    Returns:
        Decrypted data as bytes

    Raises:
        OSError: If decryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(
        ctypes.create_string_buffer(encrypted_data),
        ctypes.POINTER(ctypes.c_char)
    )
    data_in.cbData = len(encrypted_data)

    data_out = DATA_BLOB()

    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(entropy),
        ctypes.POINTER(ctypes.c_char)
    )
    entropy_blob.cbData = len(entropy)

    description_ptr = ctypes.wintypes.LPWSTR()

    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        ctypes.byref(description_ptr),
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out)
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code: {error_code}")

    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)

    return extract_data_from_blob(data_out)


def is_dpapi_available() -> bool:
    """Check if DPAPI is available on the current platform."""
    return sys.platform == "win32"
