"""
Tests for Connection-Level DNS Rebinding and SSRF Protection (Task 5.2).

Verifies:
1. safe_create_connection blocks loopback addresses when allow_local=False.
2. safe_create_connection blocks cloud metadata addresses under all conditions (even allow_local=True).
3. DNS Rebinding TOCTOU simulation: hostname resolving to a blocked IP at connection time is intercepted and rejected before TCP connect.
4. RedirectAuthProtectedSession mounts DNSRebindingSafeAdapter for both http:// and https://.
5. Outgoing requests to domains rebinding to private/metadata IPs are aborted at connection time.
"""

import os
import sys
import socket
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
import requests

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
ENGINE_ROOT = BACKEND_ROOT / "engine"
for p in [str(REPO_ROOT), str(BACKEND_ROOT), str(ENGINE_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_backend.engine.common.dns_rebinding import (
    safe_create_connection,
    DNSRebindingSafeAdapter,
    SafeHTTPConnection,
    SafeHTTPSConnection,
)
from agent_backend.engine.authentication.project_auth import RedirectAuthProtectedSession


class TestSafeCreateConnection:
    """Tests for connection-level IP verification in safe_create_connection."""

    def test_blocks_loopback_by_default(self):
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*loopback"):
            safe_create_connection(("127.0.0.1", 80), allow_local=False)

    def test_blocks_cloud_metadata_unconditionally(self):
        # Even with allow_local=True, AWS metadata 169.254.169.254 must be blocked
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*metadata"):
            safe_create_connection(("169.254.169.254", 80), allow_local=True)

    def test_blocks_alibaba_cloud_metadata_unconditionally(self):
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*metadata"):
            safe_create_connection(("100.100.100.200", 80), allow_local=True)

    def test_blocks_ipv6_loopback_by_default(self):
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*loopback"):
            safe_create_connection(("::1", 80), allow_local=False)

    def test_blocks_private_class_a(self):
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*private"):
            safe_create_connection(("10.0.0.5", 80), allow_local=False)

    def test_blocks_private_class_c(self):
        with pytest.raises(ValueError, match="SSRF / DNS Rebinding protection.*private"):
            safe_create_connection(("192.168.1.1", 80), allow_local=False)


class TestDnsRebindingToctouSimulation:
    """Simulate DNS rebinding where a domain resolves to a malicious IP at connection time."""

    @patch("socket.getaddrinfo")
    def test_dns_rebinding_to_metadata_intercepted(self, mock_getaddrinfo):
        """
        Simulate an attacker domain 'evil-rebind.com' that resolved to a public IP
        during initial URL validation, but returns 169.254.169.254 when the socket
        attempts connection.
        """
        # mock getaddrinfo returning 169.254.169.254 at connection time
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
        ]

        with pytest.raises(ValueError) as excinfo:
            safe_create_connection(("evil-rebind.com", 80), allow_local=False)

        assert "SSRF / DNS Rebinding protection" in str(excinfo.value)
        assert "169.254.169.254" in str(excinfo.value)

    @patch("socket.getaddrinfo")
    def test_dns_rebinding_to_localhost_intercepted(self, mock_getaddrinfo):
        """
        Simulate an attacker domain rebinding to 127.0.0.1 at connection time.
        """
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]

        with pytest.raises(ValueError) as excinfo:
            safe_create_connection(("rebind-localhost.com", 80), allow_local=False)

        assert "SSRF / DNS Rebinding protection" in str(excinfo.value)
        assert "127.0.0.1" in str(excinfo.value)


class TestSessionAdapterMounting:
    """Verify RedirectAuthProtectedSession mounts DNSRebindingSafeAdapter."""

    def test_session_has_rebinding_adapter_mounted(self):
        session = RedirectAuthProtectedSession()

        http_adapter = session.get_adapter("http://target-api.com")
        https_adapter = session.get_adapter("https://target-api.com")

        assert type(http_adapter).__name__ == "DNSRebindingSafeAdapter"
        assert type(https_adapter).__name__ == "DNSRebindingSafeAdapter"

    @patch("socket.getaddrinfo")
    def test_session_blocks_request_to_rebinding_host(self, mock_getaddrinfo):
        """
        Verify that a requests.Session request to a domain resolving to
        169.254.169.254 at connection time raises an error before sending HTTP data.
        """
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
        ]

        session = RedirectAuthProtectedSession(allow_local=False)
        session.trust_env = False  # Avoid proxy routing in test sandbox

        with pytest.raises((ValueError, requests.exceptions.RequestException)) as excinfo:
            session.get("http://rebinding-target.com/secret", timeout=5)

        # Confirm the underlying cause was DNS Rebinding / SSRF protection
        err_msg = str(excinfo.value)
        assert "SSRF" in err_msg or "DNS Rebinding" in err_msg or "blocked IP" in err_msg
