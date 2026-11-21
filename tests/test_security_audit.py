import sys
import os
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import requests
from fastapi.testclient import TestClient

# Setup sys.path
REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_backend.app import app
import agent_backend.db_operations as db_ops
from agent_backend.routes import projects as proj_routes
from agent_backend.auth import create_access_token
from agent_backend.engine.authentication.encryption import (
    encrypt_secret,
    decrypt_secret,
    get_encryption_key,
)
from agent_backend.engine.authentication.project_auth import (
    build_auth_headers,
    mask_secret,
    sanitize_headers,
    sanitize_text,
    RedirectAuthProtectedSession,
)
from agent_backend.engine.common.ssrf_protection import (
    validate_target_url,
    resolve_all_ips,
    is_blocked_ip,
)
from agent_backend.engine.parser.openapi_parser import load_openapi
from agent_backend.engine.test_generator.test_executor import execute_test
from agent_backend.engine.ai_analyzer.ai_failure_analyzer import analyze_failure

client = TestClient(app)

USER_ALICE = {"id": 1, "full_name": "Alice Auditor", "email": "alice.audit@example.com"}
TOKEN_ALICE = create_access_token({"sub": "1", "email": "alice.audit@example.com", "name": "Alice Auditor"})


# ==========================================================
# 1. Comprehensive SSRF Protection Tests
# ==========================================================

class TestSSRFProtections:
    @pytest.mark.parametrize("metadata_url", [
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.169.254/computeMetadata/v1",
        "http://100.100.100.200/latest/meta-data",
        "http://[fd00:ec2::254]/latest/meta-data",
    ])
    def test_cloud_metadata_blocked_even_with_local_targets_allowed(self, metadata_url):
        # Cloud metadata must be blocked under ALL configurations unconditionally
        with pytest.raises(ValueError, match="SSRF protection.*cloud metadata"):
            validate_target_url(metadata_url, allow_local=True)

        with pytest.raises(ValueError, match="SSRF protection.*cloud metadata"):
            validate_target_url(metadata_url, allow_local=False)

    @pytest.mark.parametrize("alt_ip_url", [
        "http://2130706433/sensitive",       # Decimal DWORD representation of 127.0.0.1
        "http://0x7f000001/admin",           # Hexadecimal DWORD representation of 127.0.0.1
        "http://0177.0.0.1/status",          # Octal representation of 127.0.0.1
        "http://127.1/debug",                # Shorthand 2-part IPv4
        "http://127.0.1/debug",              # Shorthand 3-part IPv4
        "http://0.0.0.0/root",               # Zero IP / unspecified
    ])
    def test_alternative_ip_representations_blocked(self, alt_ip_url):
        with pytest.raises(ValueError, match="SSRF protection"):
            validate_target_url(alt_ip_url, allow_local=False)

    @pytest.mark.parametrize("forbidden_scheme", [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://attacker.com/data",
        "gopher://127.0.0.1:6379/_FLUSHALL",
        "data:text/html;base64,PHNjcmlwdD4=",
    ])
    def test_non_http_schemes_strictly_rejected(self, forbidden_scheme):
        with pytest.raises(ValueError, match="SSRF protection.*forbidden"):
            validate_target_url(forbidden_scheme, allow_local=True)

    @pytest.mark.parametrize("private_url", [
        "http://10.0.0.1:8080/internal",
        "http://172.16.5.10:3000/metrics",
        "http://192.168.1.254/router",
        "http://[::1]:9000/api",
        "http://[fc00::1]:80/cluster",
    ])
    def test_private_and_loopback_networks_blocked_in_production(self, private_url):
        with pytest.raises(ValueError, match="SSRF protection"):
            validate_target_url(private_url, allow_local=False)

    def test_load_openapi_rejects_ssrf_metadata_target(self):
        with pytest.raises(ValueError, match="SSRF protection"):
            load_openapi("http://169.254.169.254/latest/meta-data/identity")

    def test_load_openapi_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="SSRF protection.*Scheme 'file' is forbidden"):
            load_openapi("file:///C:/Windows/win.ini")


# ==========================================================
# 2. Redirect Security & Credential Protection
# ==========================================================

class TestRedirectSecurity:
    def test_redirect_to_metadata_ip_blocked(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["Authorization", "X-API-KEY"])

        # Request redirected to AWS metadata IP
        prep_req = requests.Request(
            "GET",
            "http://169.254.169.254/latest/meta-data",
            headers={"Authorization": "Bearer secret"}
        ).prepare()

        mock_resp = MagicMock()
        mock_resp.request.url = "https://public-api.com/redirect"

        with pytest.raises(ValueError, match="SSRF protection.*cloud metadata"):
            session.rebuild_auth(prep_req, mock_resp)

    def test_redirect_to_private_ip_blocked_in_production(self):
        with patch.dict(os.environ, {"ALLOW_LOCAL_TARGETS": "false"}):
            session = RedirectAuthProtectedSession()

            prep_req = requests.Request("GET", "http://10.0.0.1/admin").prepare()
            mock_resp = MagicMock()
            mock_resp.request.url = "https://public-api.com/redirect"

            with pytest.raises(ValueError, match="SSRF protection"):
                session.rebuild_auth(prep_req, mock_resp)

    def test_credentials_stripped_on_scheme_downgrade(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["X-API-KEY"])

        # HTTPS -> HTTP on same host (downgrade vulnerability)
        prep_req = requests.Request(
            "GET",
            "http://api.secure.com/insecure-target",
            headers={"Authorization": "Bearer secret", "X-API-KEY": "api-key-99"}
        ).prepare()

        mock_resp = MagicMock()
        mock_resp.request.url = "https://api.secure.com/secure-start"

        session.rebuild_auth(prep_req, mock_resp)

        assert "Authorization" not in prep_req.headers
        assert "X-API-KEY" not in prep_req.headers

    def test_credentials_stripped_on_port_change(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["X-API-KEY"])

        # Same host, different port (cross-origin under same-origin policy)
        prep_req = requests.Request(
            "GET",
            "https://api.example.com:8443/new-port",
            headers={"Authorization": "Bearer secret", "X-API-KEY": "api-key-99"}
        ).prepare()

        mock_resp = MagicMock()
        mock_resp.request.url = "https://api.example.com:8080/old-port"

        session.rebuild_auth(prep_req, mock_resp)

        assert "Authorization" not in prep_req.headers
        assert "X-API-KEY" not in prep_req.headers

    def test_multiple_redirect_hops_cannot_restore_credentials(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["X-API-KEY"])

        # Hop 1: api.com -> evil.com (cross-host redirect)
        prep_req = requests.Request(
            "GET",
            "https://evil.com/capture",
            headers={"Authorization": "Bearer secret", "X-API-KEY": "api-key-99", "Accept": "application/json"}
        ).prepare()

        mock_resp_1 = MagicMock()
        mock_resp_1.request.url = "https://api.com/start"

        session.rebuild_auth(prep_req, mock_resp_1)

        # Credentials stripped on Hop 1
        assert "Authorization" not in prep_req.headers
        assert "X-API-KEY" not in prep_req.headers

        # Hop 2: evil.com -> api.com/finish (redirect back to original host)
        prep_req.url = "https://api.com/finish"
        mock_resp_2 = MagicMock()
        mock_resp_2.request.url = "https://evil.com/capture"

        session.rebuild_auth(prep_req, mock_resp_2)

        # Credentials MUST NOT be re-injected on subsequent hops
        assert "Authorization" not in prep_req.headers
        assert "X-API-KEY" not in prep_req.headers

    def test_disallow_cross_origin_redirects_option(self):
        session = RedirectAuthProtectedSession(
            sensitive_headers=["X-API-KEY"],
            disallow_cross_origin_redirects=True
        )

        prep_req = requests.Request("GET", "https://third-party.com/target").prepare()
        mock_resp = MagicMock()
        mock_resp.request.url = "https://my-api.com/source"

        with pytest.raises(ValueError, match="cross-origin redirect.*disallowed"):
            session.rebuild_auth(prep_req, mock_resp)


# ==========================================================
# 3. Encryption Security & Key Isolation
# ==========================================================

class TestEncryptionAudit:
    def test_no_plaintext_fallback_on_corrupt_data(self):
        corrupt_payload = base64.b64encode(b"012345678901corrupted_ciphertext_data_without_tag").decode()
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_secret(corrupt_payload)

    def test_wrong_key_fails_securely(self):
        key1 = b"\x01" * 32
        key2 = b"\x02" * 32

        encrypted = encrypt_secret("confidential-token", key=key1)

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_secret(encrypted, key=key2)

    def test_encryption_key_requires_32_bytes(self):
        # 16-byte key (AES-128) must be rejected because platform standard is AES-256
        with pytest.raises(ValueError, match="must be exactly 32 bytes"):
            get_encryption_key(custom_key=b"1234567890123456")


# ==========================================================
# 4. Credential Leakage Prevention Across Subsystems
# ==========================================================

class TestCredentialLeakagePrevention:
    def test_error_logs_and_exceptions_sanitize_secrets(self):
        raw_err = "Failed connecting with token: eyJhbGciOiAiSFMyNTYi... and key sec-987654321"
        sanitized = sanitize_text(raw_err, secret="sec-987654321")
        assert "sec-987654321" not in sanitized
        assert "********" in sanitized

    def test_ai_analyzer_prompt_masks_bearer_token(self):
        # Create a mock failed test with a token in the failure reason
        failed_result = {
            "test_id": "TC-SEC-1",
            "endpoint": "/v1/auth-check",
            "method": "POST",
            "request": {"headers": {"Authorization": "Bearer super-secret-value-1234"}},
            "expected": {"status_code": 200},
            "actual": {"status_code": 401, "body": {"error": "Invalid token"}},
            "failure_reason": "Header Authorization: Bearer super-secret-value-1234 was rejected"
        }

        with patch("agent_backend.engine.ai_analyzer.ai_failure_analyzer.client") as mock_client:
            mock_chat = MagicMock()
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock(message=MagicMock(content='{"summary": "Auth failed", "possible_cause": "Expired", "severity": "High", "recommendation": "Renew"}'))]
            mock_chat.create.return_value = mock_resp
            mock_client.chat.completions = mock_chat

            analyze_failure(failed_result)

            call_args = mock_chat.create.call_args[1]
            sent_content = call_args["messages"][0]["content"]

            # Confirm plaintext token was masked before sending to Gemini
            assert "super-secret-value-1234" not in sent_content
            assert "Bearer ********" in sent_content

    def test_openapi_endpoint_discovery_sanitizes_errors(self):
        mock_project = {
            "id": 200,
            "user_id": 1,
            "project_name": "Error Spec Project",
            "base_url": "https://api.error.com",
            "openapi_url": "https://api.error.com/openapi.json",
            "auth_type": "bearer",
            "auth_secret_encrypted": encrypt_secret("my-jwt-leaked-check"),
            "has_credentials": True,
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_ALICE), \
             patch.object(proj_routes.db_operations, "get_project_by_id", return_value=mock_project), \
             patch("agent_backend.routes.projects.load_openapi", side_effect=ValueError("Failed auth with token: my-jwt-leaked-check")):

            resp = client.get("/projects/200/endpoints", headers={"Authorization": f"Bearer {TOKEN_ALICE}"})

            assert resp.status_code == 400
            detail = resp.json()["detail"]
            # Error response MUST NOT reveal the decrypted secret
            assert "my-jwt-leaked-check" not in detail
            assert "********" in detail
