"""
Centralized Response & Secret Data Sanitizer.

Provides exact-secret redaction and data sanitization across:
- API response bodies and headers
- Test execution results
- Database persistence (test_results, bug_reports, test_runs)
- Gemini AI failure analysis prompts
- Error messages and exception traces
"""

import json
import re
from typing import Any, Dict, List, Optional, Iterable, Set, Union


DEFAULT_REDACTION_PLACEHOLDER = "[REDACTED]"

_COMMON_AUTH_HEADER_PREFIXES = [
    re.compile(r"^Bearer\s+", re.IGNORECASE),
    re.compile(r"^Basic\s+", re.IGNORECASE),
    re.compile(r"^Token\s+", re.IGNORECASE),
]


def extract_project_secrets(
    project: Optional[Dict[str, Any]] = None,
    auth_headers: Optional[Dict[str, Any]] = None,
    extra_secrets: Optional[Iterable[Optional[str]]] = None
) -> List[str]:
    """
    Extract all raw sensitive secret strings associated with a project or test run.
    Safely decrypts encrypted project secrets if present.
    Filters out empty, whitespace-only, or trivial short strings (<3 chars).
    Returns secrets sorted by length in descending order to prioritize longer matches.
    """
    candidates: Set[str] = set()

    # 1. Extract from project dictionary
    if isinstance(project, dict):
        # Plaintext secret if present in memory
        raw_sec = project.get("auth_secret")
        if isinstance(raw_sec, str) and raw_sec.strip():
            candidates.add(raw_sec.strip())

        # Encrypted secret from database
        enc_sec = project.get("auth_secret_encrypted")
        if isinstance(enc_sec, str) and enc_sec.strip():
            try:
                try:
                    from engine.authentication.encryption import decrypt_secret
                except ImportError:
                    from agent_backend.engine.authentication.encryption import decrypt_secret
                decrypted = decrypt_secret(enc_sec.strip())
                if decrypted and decrypted.strip():
                    candidates.add(decrypted.strip())
            except Exception:
                pass

    # 2. Extract from configured auth headers
    if isinstance(auth_headers, dict):
        for header_name, header_val in auth_headers.items():
            if not isinstance(header_val, str) or not header_val.strip():
                continue
            val_clean = header_val.strip()
            # Strip standard scheme prefixes (e.g. 'Bearer ') to extract the raw token
            stripped_val = val_clean
            for prefix_pattern in _COMMON_AUTH_HEADER_PREFIXES:
                stripped_val = prefix_pattern.sub("", stripped_val).strip()

            if stripped_val:
                candidates.add(stripped_val)
            if val_clean != stripped_val:
                candidates.add(val_clean)

    # 3. Extra caller-provided secrets
    if extra_secrets:
        for s in extra_secrets:
            if isinstance(s, str) and s.strip():
                candidates.add(s.strip())

    # Filter out empty, whitespace, or trivial secrets (<3 chars)
    # to prevent accidentally replacing common characters or numbers
    valid_secrets = [
        s for s in candidates
        if len(s) >= 3 and not s.isspace()
    ]

    # Sort descending by length so longer substrings are matched and redacted first
    valid_secrets.sort(key=len, reverse=True)
    return valid_secrets


def sanitize_string(
    text: Optional[str],
    secrets: Optional[Iterable[Optional[str]]] = None,
    placeholder: str = DEFAULT_REDACTION_PLACEHOLDER
) -> Optional[str]:
    """
    Sanitize a string by replacing all exact occurrences of configured secrets
    with placeholder (default: '[REDACTED]').
    Also performs secondary pattern-based redaction for lingering Bearer or API Key headers.
    """
    if text is None:
        return None

    if not isinstance(text, str):
        text = str(text)

    if not text:
        return text

    sanitized = text

    # 1. Exact secret substring replacement (longest secrets first)
    if secrets:
        # Collect and sort non-empty secrets
        clean_secrets: List[str] = []
        for s in secrets:
            if isinstance(s, str) and len(s) >= 3 and not s.isspace():
                clean_secrets.append(s)
        clean_secrets.sort(key=len, reverse=True)

        for secret in clean_secrets:
            if secret in sanitized:
                sanitized = sanitized.replace(secret, placeholder)

    # 2. Pattern-based redaction for common sensitive headers in JSON or text (skip if already redacted/masked)
    sanitized = re.sub(
        r'(?i)(["\']?Authorization["\']?\s*:\s*["\']?Bearer\s+)(?!\[REDACTED\]|\*{4,})[A-Za-z0-9\-_\.~+/=]+',
        r"\g<1>********",
        sanitized
    )
    sanitized = re.sub(
        r'(?i)(["\']?X-API-KEY["\']?\s*:\s*["\']?)(?!\[REDACTED\]|\*{4,})[^\s,;\"\'}{]+',
        r"\g<1>********",
        sanitized
    )

    return sanitized


def sanitize_data(
    data: Any,
    secrets: Optional[Iterable[Optional[str]]] = None,
    placeholder: str = DEFAULT_REDACTION_PLACEHOLDER
) -> Any:
    """
    Recursively sanitize any data structure (dict, list, tuple, str, int, float, bool, None).
    Replaces exact occurrences of configured sensitive values with placeholder.
    Preserves dictionary keys, list hierarchies, and non-string primitive types.
    Handles embedded JSON strings gracefully.
    """
    if data is None:
        return None

    # Strings
    if isinstance(data, str):
        sanitized_str = sanitize_string(data, secrets, placeholder)
        # Check if the string was serialized JSON; if so, verify it remains valid JSON
        if (sanitized_str.startswith("{") and sanitized_str.endswith("}")) or \
           (sanitized_str.startswith("[") and sanitized_str.endswith("]")):
            try:
                # If it's valid JSON, ensure embedded structures are also sanitized
                parsed = json.loads(sanitized_str)
                re_sanitized = sanitize_data(parsed, secrets, placeholder)
                return json.dumps(re_sanitized)
            except Exception:
                pass
        return sanitized_str

    # Dictionaries
    if isinstance(data, dict):
        sanitized_dict = {}
        for k, v in data.items():
            clean_key = sanitize_data(k, secrets, placeholder)
            clean_val = sanitize_data(v, secrets, placeholder)
            sanitized_dict[clean_key] = clean_val
        return sanitized_dict

    # Lists
    if isinstance(data, list):
        return [sanitize_data(item, secrets, placeholder) for item in data]

    # Tuples
    if isinstance(data, tuple):
        return tuple(sanitize_data(item, secrets, placeholder) for item in data)

    # Sets
    if isinstance(data, set):
        return {sanitize_data(item, secrets, placeholder) for item in data}

    # Primitives (int, float, bool, etc.) are safe as-is
    return data


def sanitize_error_message(
    error: Union[Exception, str, Any],
    sensitive_strings: Optional[Iterable[Optional[str]]] = None,
    max_length: int = 500
) -> str:
    """
    Sanitize an error message or exception trace for safe persistence in test_runs.error_message
    and transmission to frontend clients.
    - Redacts exact sensitive secret substrings (e.g. API keys, auth secrets).
    - Redacts Bearer tokens (e.g. 'Bearer eyJhbGci...').
    - Redacts passwords and credentials in URLs (e.g. 'mysql://user:pass@host').
    - Redacts common query param passwords/keys (e.g. 'password=xyz', 'api_key=xyz').
    - Truncates to max_length (default 500) characters cleanly.
    """
    if error is None:
        return ""

    text = str(error).strip()
    if not text:
        return ""

    # 1. Exact secret redaction
    sanitized = sanitize_string(text, secrets=sensitive_strings) or ""

    # 2. Redact Bearer tokens in headers or strings
    sanitized = re.sub(r'(?i)bearer\s+[A-Za-z0-9\-_\.~+/=]+', 'Bearer [REDACTED]', sanitized)

    # 3. Redact Basic auth or user:pass in URLs (http://user:pass@host:port)
    sanitized = re.sub(r'([a-zA-Z0-9+]+://)([^:\s]+):([^@\s]+)@', r'\1[REDACTED]@[REDACTED]', sanitized)

    # 4. Redact sensitive query parameters / key-value pairs
    sanitized = re.sub(r'(?i)(password|secret|token|api_?key|auth)\s*[:=]\s*["\']?[^\s&,"\']+', r'\1=[REDACTED]', sanitized)

    # 5. Clean whitespace and truncate
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."

    return sanitized

