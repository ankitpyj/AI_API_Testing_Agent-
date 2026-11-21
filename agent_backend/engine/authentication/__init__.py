"""
Authentication & Encryption Engine for Project Target APIs.
"""

from .encryption import encrypt_secret, decrypt_secret, get_encryption_key
from .project_auth import (
    build_auth_headers,
    mask_secret,
    sanitize_headers,
    sanitize_text,
    RedirectAuthProtectedSession,
    validate_auth_header_name,
)

__all__ = [
    "encrypt_secret",
    "decrypt_secret",
    "get_encryption_key",
    "build_auth_headers",
    "mask_secret",
    "sanitize_headers",
    "sanitize_text",
    "RedirectAuthProtectedSession",
    "validate_auth_header_name",
]
