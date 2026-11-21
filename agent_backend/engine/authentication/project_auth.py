"""
Project Target API Authentication & Credential Injection Layer.
Supports Public (None), Bearer Token, and API Key authentication.
Enforces header sanitization, secret masking, and cross-host redirect protection.
"""

import re
from typing import Optional, Dict, Any, Iterable
import requests
from requests.sessions import SessionRedirectMixin


_VALID_HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9\-_]{1,100}$")
_DEFAULT_API_KEY_HEADER = "X-API-KEY"

_COMMON_SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "x-auth-token",
    "proxy-authorization",
}


def validate_auth_header_name(header_name: Optional[str]) -> str:
    """
    Validate an HTTP header name to prevent header injection and malformed headers.
    Must consist only of alphanumeric characters, hyphens, and underscores.
    """
    if not header_name:
        return _DEFAULT_API_KEY_HEADER

    cleaned = header_name.strip()
    if not _VALID_HEADER_NAME_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid header name '{header_name}'. Header names must only contain "
            "alphanumeric characters, hyphens, and underscores (1-100 characters)."
        )
    return cleaned


def build_auth_headers(
    auth_type: Optional[str] = "none",
    auth_header_name: Optional[str] = None,
    auth_secret: Optional[str] = None
) -> Dict[str, str]:
    """
    Construct HTTP headers dictionary for the configured project authentication type.
    Supported types:
      - 'none' (or empty): returns {}
      - 'bearer': returns {'Authorization': 'Bearer <token>'}
      - 'api_key': returns {<auth_header_name or 'X-API-KEY'>: '<token>'}
    """
    normalized_type = (auth_type or "none").strip().lower()

    if normalized_type == "none":
        return {}

    if normalized_type == "bearer":
        if not auth_secret or not auth_secret.strip():
            return {}
        return {"Authorization": f"Bearer {auth_secret.strip()}"}

    if normalized_type == "api_key":
        header_name = validate_auth_header_name(auth_header_name)
        if not auth_secret or not auth_secret.strip():
            return {}
        return {header_name: auth_secret.strip()}

    raise ValueError(
        f"Unsupported auth_type: '{auth_type}'. Supported types are 'none', 'bearer', and 'api_key'."
    )


def mask_secret(secret: Optional[str]) -> str:
    """
    Mask a sensitive credential for safe presentation.
    """
    if not secret:
        return ""
    return "********"


def sanitize_headers(
    headers: Optional[Dict[str, Any]],
    secret: Optional[str] = None,
    sensitive_header_names: Optional[Iterable[str]] = None
) -> Dict[str, str]:
    """
    Produce a sanitized, display-safe copy of an HTTP headers dictionary.
    Replaces sensitive header values and secret substrings with '********'.
    """
    if not headers:
        return {}

    sensitive_set = set(_COMMON_SENSITIVE_HEADERS)
    if sensitive_header_names:
        for name in sensitive_header_names:
            if name:
                sensitive_set.add(name.strip().lower())

    sanitized = {}
    for k, v in headers.items():
        key_str = str(k)
        val_str = str(v)
        key_lower = key_str.lower()

        # 1. Mask if header key is sensitive
        if key_lower in sensitive_set or "api-key" in key_lower or "token" in key_lower or "secret" in key_lower:
            if key_lower == "authorization" and val_str.lower().startswith("bearer "):
                sanitized[key_str] = "Bearer ********"
            else:
                sanitized[key_str] = "********"
            continue

        # 2. Mask secret value if it occurs in any other header value
        if secret and secret in val_str:
            sanitized[key_str] = val_str.replace(secret, "********")
        else:
            sanitized[key_str] = val_str

    return sanitized


def sanitize_text(text: Optional[str], secret: Optional[str] = None) -> Optional[str]:
    """
    Sanitize text strings (e.g., log lines, error messages, bug report summaries, JSON dumps)
    to prevent accidental credential leakage.
    """
    if not text:
        return text

    sanitized = str(text)

    # 1. Direct secret string replacement
    if secret and len(secret) > 0 and secret in sanitized:
        sanitized = sanitized.replace(secret, "********")

    # 2. Pattern-based masking for Bearer tokens in plaintext and JSON
    sanitized = re.sub(
        r'(?i)(["\']?Authorization["\']?\s*:\s*["\']?Bearer\s+)[A-Za-z0-9\-_\.~+/=]+',
        r"\g<1>********",
        sanitized
    )

    # 3. Pattern-based masking for standalone Bearer tokens
    sanitized = re.sub(
        r'(?i)(\bBearer\s+)[A-Za-z0-9\-_\.~+/=]{8,}',
        r"\g<1>********",
        sanitized
    )

    # 4. Pattern-based masking for standard API Key headers in plaintext and JSON
    sanitized = re.sub(
        r'(?i)(["\']?X-API-KEY["\']?\s*:\s*["\']?)[^\s,;\"\'}{]+',
        r"\g<1>********",
        sanitized
    )

    return sanitized


try:
    from engine.common.ssrf_protection import validate_target_url
except ImportError:
    try:
        from common.ssrf_protection import validate_target_url
    except ImportError:
        from agent_backend.engine.common.ssrf_protection import validate_target_url

try:
    from engine.common.dns_rebinding import DNSRebindingSafeAdapter
except ImportError:
    try:
        from common.dns_rebinding import DNSRebindingSafeAdapter
    except ImportError:
        try:
            from agent_backend.engine.common.dns_rebinding import DNSRebindingSafeAdapter
        except ImportError:
            DNSRebindingSafeAdapter = None


class RedirectAuthProtectedSession(requests.Session):
    """
    A requests.Session that protects sensitive authentication credentials,
    enforces socket-level DNS rebinding defense, and blocks SSRF attacks on redirects.
    
    1. Validates destination IP at socket connection time before TCP handshake (DNS rebinding protection).
    2. Blocks redirects to private IP addresses, loopback, or cloud metadata endpoints.
    3. Strips Authorization and custom sensitive headers on cross-origin redirects.
    4. Option to disallow cross-origin redirects for authenticated requests.
    """

    def __init__(
        self,
        sensitive_headers: Optional[Iterable[str]] = None,
        secret: Optional[str] = None,
        disallow_cross_origin_redirects: bool = False,
        allow_local: Optional[bool] = None
    ):
        super().__init__()
        self.sensitive_headers = set(_COMMON_SENSITIVE_HEADERS)
        if sensitive_headers:
            for h in sensitive_headers:
                if h:
                    self.sensitive_headers.add(h.strip().lower())
        self.secret = secret
        self.disallow_cross_origin_redirects = disallow_cross_origin_redirects

        if allow_local is None:
            import os
            self.allow_local = os.getenv("ALLOW_LOCAL_TARGETS", "false").lower() in ("true", "1", "yes")
        else:
            self.allow_local = allow_local

        # Mount connection-level DNS rebinding and SSRF protection adapter
        if DNSRebindingSafeAdapter is not None:
            adapter = DNSRebindingSafeAdapter(allow_local=self.allow_local)
            self.mount("http://", adapter)
            self.mount("https://", adapter)

    def rebuild_auth(self, prepared_request, response):
        """
        When a redirect occurs:
          1. Verify the redirect destination URL does not violate SSRF policies.
          2. Check if the redirect is cross-origin (scheme, host, port).
          3. Strip sensitive authentication headers if crossing origins.
        """
        super().rebuild_auth(prepared_request, response)

        # 1. SSRF Protection: validate redirect destination
        if prepared_request.url:
            validate_target_url(prepared_request.url, allow_local=self.allow_local)

        # 2. Check if redirect crosses origin boundaries (scheme, host, or port)
        if self.should_strip_auth(response.request.url, prepared_request.url):
            if self.disallow_cross_origin_redirects:
                raise ValueError(
                    f"Redirect rejected: cross-origin redirect from {response.request.url} "
                    f"to {prepared_request.url} is disallowed for authenticated requests."
                )

            # Strip all sensitive headers case-insensitively
            keys_to_remove = [
                k for k in prepared_request.headers.keys()
                if k.lower() in self.sensitive_headers
            ]
            for k in keys_to_remove:
                prepared_request.headers.pop(k, None)

            # Also strip any header whose value contains the secret substring
            if self.secret:
                val_keys_to_remove = [
                    k for k, v in prepared_request.headers.items()
                    if self.secret in str(v)
                ]
                for k in val_keys_to_remove:
                    prepared_request.headers.pop(k, None)
