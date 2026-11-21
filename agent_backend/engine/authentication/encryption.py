"""
Secure encryption module for project API credentials using AES-256-GCM.
Plaintext secrets are never stored directly in the database or logs.
"""

import os
import base64
import binascii
import secrets
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

# Ensure env vars are loaded from agent_backend/.env if not present
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def get_encryption_key(custom_key: Optional[str | bytes] = None) -> bytes:
    """
    Resolve and validate the 256-bit (32-byte) key for AES-GCM operations.
    Supports:
      - 32 raw bytes
      - 64-char hexadecimal string
      - Standard base64-encoded 32-byte string
      - 32-character UTF-8 string
    Raises ValueError if key is missing or invalid.
    """
    raw = custom_key if custom_key is not None else os.getenv("PROJECT_SECRET_ENCRYPTION_KEY")
    if not raw:
        raise ValueError(
            "PROJECT_SECRET_ENCRYPTION_KEY is not configured. "
            "Please set a 32-byte key (64 hex characters or 44 base64 characters) in the environment."
        )

    if isinstance(raw, bytes):
        if len(raw) == 32:
            return raw
        raise ValueError(f"Raw encryption key must be exactly 32 bytes, got {len(raw)} bytes.")

    raw_str = raw.strip()

    # 1. Try 64-character hex
    if len(raw_str) == 64:
        try:
            key_bytes = binascii.unhexlify(raw_str)
            if len(key_bytes) == 32:
                return key_bytes
        except Exception:
            pass

    # 2. Try base64 decoding
    try:
        b64_bytes = base64.b64decode(raw_str, validate=True)
        if len(b64_bytes) == 32:
            return b64_bytes
    except Exception:
        pass

    # 3. Try UTF-8 string of length 32
    utf8_bytes = raw_str.encode("utf-8")
    if len(utf8_bytes) == 32:
        return utf8_bytes

    raise ValueError(
        f"PROJECT_SECRET_ENCRYPTION_KEY is invalid. Expected a 32-byte key (64 hex chars or 44 base64 chars), "
        f"but received an incompatible format or length ({len(raw_str)} chars)."
    )


def generate_key() -> str:
    """
    Generate a fresh 256-bit cryptographically secure key formatted as a 64-character hex string.
    """
    return secrets.token_hex(32)


def encrypt_secret(plaintext: str, key: Optional[bytes] = None) -> str:
    """
    Encrypt a plaintext secret using AES-256-GCM.
    Returns base64-encoded payload: nonce (12 bytes) + ciphertext + tag (16 bytes).
    """
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    if plaintext == "":
        return ""

    key_bytes = key or get_encryption_key()
    aesgcm = AESGCM(key_bytes)

    # 96-bit (12-byte) cryptographically secure random nonce
    nonce = os.urandom(12)
    ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    # Pack nonce + ciphertext_and_tag into base64
    payload = nonce + ciphertext_and_tag
    return base64.b64encode(payload).decode("ascii")


def decrypt_secret(encrypted_b64: str, key: Optional[bytes] = None) -> str:
    """
    Decrypt a base64-encoded AES-256-GCM payload.
    Verifies authentication tag and returns original plaintext string.
    Raises ValueError if payload is corrupted, truncated, or key is invalid.
    """
    if not encrypted_b64:
        return ""

    key_bytes = key or get_encryption_key()
    aesgcm = AESGCM(key_bytes)

    try:
        raw = base64.b64decode(encrypted_b64)
    except Exception as e:
        raise ValueError(f"Corrupted or invalid base64 encrypted payload: {str(e)}") from e

    if len(raw) < 12 + 16:  # 12-byte nonce + 16-byte authentication tag
        raise ValueError("Encrypted secret payload is truncated or incomplete.")

    nonce = raw[:12]
    ciphertext_and_tag = raw[12:]

    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
        return plaintext_bytes.decode("utf-8")
    except InvalidTag as e:
        raise ValueError("Decryption failed: cryptographic tag verification failed or key is incorrect.") from e
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}") from e
