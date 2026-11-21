import sys
import os
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import requests
from fastapi.testclient import TestClient

# Setup sys.path to ensure agent_backend can be imported
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
    generate_key,
)
from agent_backend.engine.authentication.project_auth import (
    build_auth_headers,
    mask_secret,
    sanitize_headers,
    sanitize_text,
    validate_auth_header_name,
    RedirectAuthProtectedSession,
)
from agent_backend.engine.test_generator.test_executor import execute_test

client = TestClient(app)

USER_A = {"id": 1, "full_name": "Alice Developer", "email": "alice@example.com"}
USER_B = {"id": 2, "full_name": "Bob Hacker", "email": "bob@example.com"}

TOKEN_A = create_access_token({"sub": "1", "email": "alice@example.com", "name": "Alice Developer"})
TOKEN_B = create_access_token({"sub": "2", "email": "bob@example.com", "name": "Bob Hacker"})

TEST_SECRET_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


# ==========================================================
# 1. AES-256-GCM Encryption & Decryption Unit Tests
# ==========================================================

class TestAES256GCMEncryption:
    def test_encrypt_and_decrypt_cycle(self):
        plain = "super-secret-production-token-xyz-12345"
        encrypted = encrypt_secret(plain)
        assert encrypted != plain
        assert len(encrypted) > 30

        decrypted = decrypt_secret(encrypted)
        assert decrypted == plain

    def test_distinct_nonces_produce_different_ciphertexts(self):
        plain = "constant-api-key"
        c1 = encrypt_secret(plain)
        c2 = encrypt_secret(plain)
        assert c1 != c2
        assert decrypt_secret(c1) == plain
        assert decrypt_secret(c2) == plain

    def test_tampered_ciphertext_fails_integrity(self):
        encrypted = encrypt_secret("sensitive-credentials")
        raw = bytearray(base64.b64decode(encrypted))
        # Tamper with the ciphertext/tag bytes
        raw[-1] ^= 0xFF
        tampered_b64 = base64.b64encode(raw).decode("ascii")

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_secret(tampered_b64)

    def test_missing_encryption_key_raises_error(self):
        with patch.dict(os.environ, {"PROJECT_SECRET_ENCRYPTION_KEY": ""}):
            with pytest.raises(ValueError, match="PROJECT_SECRET_ENCRYPTION_KEY is not configured"):
                get_encryption_key()

    def test_invalid_key_length_rejected(self):
        with patch.dict(os.environ, {"PROJECT_SECRET_ENCRYPTION_KEY": "too-short"}):
            with pytest.raises(ValueError, match="invalid"):
                get_encryption_key()


# ==========================================================
# 2. Project Target API Authentication Header Construction
# ==========================================================

class TestProjectAuthHeaders:
    def test_build_none_auth_headers(self):
        assert build_auth_headers("none") == {}
        assert build_auth_headers(None) == {}

    def test_build_bearer_auth_headers(self):
        headers = build_auth_headers("bearer", auth_secret="my-bearer-token")
        assert headers == {"Authorization": "Bearer my-bearer-token"}

    def test_build_api_key_auth_headers(self):
        headers = build_auth_headers("api_key", auth_header_name="X-API-KEY", auth_secret="secret-key-999")
        assert headers == {"X-API-KEY": "secret-key-999"}

    def test_custom_api_key_header_name(self):
        headers = build_auth_headers("api_key", auth_header_name="X-Custom-Tenant-Auth", auth_secret="tenant-123")
        assert headers == {"X-Custom-Tenant-Auth": "tenant-123"}

    def test_unsupported_auth_type_rejected(self):
        with pytest.raises(ValueError, match="Unsupported auth_type"):
            build_auth_headers("basic", auth_secret="user:pass")

    def test_invalid_header_name_characters_rejected(self):
        with pytest.raises(ValueError, match="Invalid header name"):
            validate_auth_header_name("Invalid Header: Name\r\n")

        with pytest.raises(ValueError, match="Invalid header name"):
            validate_auth_header_name("Header Name With Spaces")


# ==========================================================
# 3. Secret Masking & Sanitization
# ==========================================================

class TestSecretMaskingAndSanitization:
    def test_mask_secret(self):
        assert mask_secret("secret123") == "********"
        assert mask_secret("") == ""

    def test_sanitize_headers(self):
        raw_headers = {
            "Authorization": "Bearer sensitive-secret-token",
            "X-API-KEY": "secret-api-key-val",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        sanitized = sanitize_headers(raw_headers, secret="sensitive-secret-token")
        assert sanitized["Authorization"] == "Bearer ********"
        assert sanitized["X-API-KEY"] == "********"
        assert sanitized["Content-Type"] == "application/json"
        assert sanitized["Accept"] == "application/json"

    def test_sanitize_text(self):
        raw_log = "Executing test with Authorization: Bearer eyJhbGciOi... and secret key 999111"
        sanitized = sanitize_text(raw_log, secret="999111")
        assert "999111" not in sanitized
        assert "********" in sanitized


# ==========================================================
# 4. Cross-Host Redirect Credential Protection
# ==========================================================

class TestCrossHostRedirectProtection:
    def test_sensitive_headers_stripped_on_cross_host_redirect(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["X-API-KEY", "Authorization"])

        # Create a mock request pointing to example.com with sensitive headers
        prep_req = requests.Request(
            "GET",
            "https://target-api.com/profile",
            headers={"Authorization": "Bearer token", "X-API-KEY": "secret", "Accept": "application/json"}
        ).prepare()

        # Create mock response indicating redirect to third-party domain
        mock_resp = MagicMock()
        mock_resp.request.url = "https://target-api.com/profile"
        prep_req.url = "https://malicious-tracker.com/steal"

        session.rebuild_auth(prep_req, mock_resp)

        # Cross-host redirect MUST strip sensitive headers
        assert "Authorization" not in prep_req.headers
        assert "X-API-KEY" not in prep_req.headers
        assert prep_req.headers.get("Accept") == "application/json"

    def test_sensitive_headers_preserved_on_same_host_redirect(self):
        session = RedirectAuthProtectedSession(sensitive_headers=["X-API-KEY"])

        prep_req = requests.Request(
            "GET",
            "https://target-api.com/old-endpoint",
            headers={"X-API-KEY": "secret", "Accept": "application/json"}
        ).prepare()

        mock_resp = MagicMock()
        mock_resp.request.url = "https://target-api.com/old-endpoint"
        prep_req.url = "https://target-api.com/new-endpoint"

        session.rebuild_auth(prep_req, mock_resp)

        # Same-host redirect preserves credentials
        assert prep_req.headers.get("X-API-KEY") == "secret"


# ==========================================================
# 5. Project API Endpoints with Authentication Config
# ==========================================================

class TestProjectAPIAuthenticationEndpoints:
    def test_create_project_with_bearer_auth(self):
        created = {
            "id": 101,
            "user_id": 1,
            "project_name": "Secured Bearer API",
            "base_url": "https://api.secure.com",
            "openapi_url": None,
            "auth_type": "bearer",
            "auth_header_name": None,
            "has_credentials": True,
            "created_at": "2026-11-19 00:00:00",
            "updated_at": "2026-11-19 00:00:00",
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
             patch.object(proj_routes.db_operations, "create_project", return_value=created) as mock_create:

            resp = client.post(
                "/projects",
                json={
                    "project_name": "Secured Bearer API",
                    "base_url": "https://api.secure.com",
                    "auth_type": "bearer",
                    "auth_secret": "my-secret-jwt-token"
                },
                headers={"Authorization": f"Bearer {TOKEN_A}"}
            )

            assert resp.status_code == 201
            data = resp.json()["data"]
            assert data["auth_type"] == "bearer"
            assert data["has_credentials"] is True
            # Never leak plaintext secret or ciphertext in API response
            assert "auth_secret" not in data
            assert "auth_secret_encrypted" not in data

            # Verify encrypted secret was passed to DB create
            _, kwargs = mock_create.call_args
            assert kwargs["auth_type"] == "bearer"
            assert kwargs["auth_secret_encrypted"] is not None
            assert kwargs["auth_secret_encrypted"] != "my-secret-jwt-token"
            assert decrypt_secret(kwargs["auth_secret_encrypted"]) == "my-secret-jwt-token"

    def test_create_project_with_api_key_auth(self):
        created = {
            "id": 102,
            "user_id": 1,
            "project_name": "Secured API Key API",
            "base_url": "https://api.apikey.com",
            "auth_type": "api_key",
            "auth_header_name": "X-CUSTOM-KEY",
            "has_credentials": True,
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
             patch.object(proj_routes.db_operations, "create_project", return_value=created) as mock_create:

            resp = client.post(
                "/projects",
                json={
                    "project_name": "Secured API Key API",
                    "base_url": "https://api.apikey.com",
                    "auth_type": "api_key",
                    "auth_header_name": "X-CUSTOM-KEY",
                    "auth_secret": "secret_key_abc_123"
                },
                headers={"Authorization": f"Bearer {TOKEN_A}"}
            )

            assert resp.status_code == 201
            data = resp.json()["data"]
            assert data["auth_type"] == "api_key"
            assert data["auth_header_name"] == "X-CUSTOM-KEY"
            assert data["has_credentials"] is True

            _, kwargs = mock_create.call_args
            assert kwargs["auth_header_name"] == "X-CUSTOM-KEY"
            assert decrypt_secret(kwargs["auth_secret_encrypted"]) == "secret_key_abc_123"

    def test_create_project_missing_required_secret_rejected(self):
        with patch.object(db_ops, "get_user_by_id", return_value=USER_A):
            resp = client.post(
                "/projects",
                json={
                    "project_name": "Bad Project",
                    "base_url": "https://api.example.com",
                    "auth_type": "bearer",
                    "auth_secret": ""
                },
                headers={"Authorization": f"Bearer {TOKEN_A}"}
            )
            assert resp.status_code == 422
            assert "auth_secret is required" in resp.json()["detail"]

    def test_unsupported_auth_type_rejected(self):
        with patch.object(db_ops, "get_user_by_id", return_value=USER_A):
            resp = client.post(
                "/projects",
                json={
                    "project_name": "Bad Auth",
                    "base_url": "https://api.example.com",
                    "auth_type": "basic",
                    "auth_secret": "secret"
                },
                headers={"Authorization": f"Bearer {TOKEN_A}"}
            )
            assert resp.status_code == 422
            assert "Invalid auth_type" in resp.json()["detail"]

    def test_get_project_never_leaks_secrets(self):
        mock_proj = {
            "id": 101,
            "user_id": 1,
            "project_name": "Secured Bearer API",
            "base_url": "https://api.secure.com",
            "openapi_url": None,
            "auth_type": "bearer",
            "auth_header_name": None,
            "has_credentials": True,
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
             patch.object(proj_routes.db_operations, "get_project_by_id", return_value=mock_proj):

            resp = client.get("/projects/101", headers={"Authorization": f"Bearer {TOKEN_A}"})
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["has_credentials"] is True
            assert "auth_secret" not in data
            assert "auth_secret_encrypted" not in data

    def test_user_b_cannot_access_user_a_project_credentials(self):
        mock_proj_a = {
            "id": 101,
            "user_id": 1,
            "project_name": "Alice Secured API",
            "base_url": "https://api.alice.com",
            "auth_type": "bearer",
            "has_credentials": True
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_B), \
             patch.object(proj_routes.db_operations, "get_project_by_id", return_value=mock_proj_a):

            resp = client.get("/projects/101", headers={"Authorization": f"Bearer {TOKEN_B}"})
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Project not found"


# ==========================================================
# 6. Test Executor Authentication Injection
# ==========================================================

class TestExecutorAuthenticationInjection:
    def test_execute_test_injects_bearer_auth(self):
        test_case = {
            "test_id": "TC-AUTH-1",
            "method": "GET",
            "endpoint": "/protected/resource",
            "request": {"headers": {"Accept": "application/json"}},
            "expected": {"status_code": 200}
        }

        auth_headers = {"Authorization": "Bearer valid-access-token"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}

        with patch("requests.sessions.Session.request", return_value=mock_resp) as mock_req:
            result = execute_test(test_case, base_url="http://127.0.0.1:8000", auth_headers=auth_headers)

            assert result["actual"]["status_code"] == 200

            # Verify actual outbound request contained the Bearer token
            _, kwargs = mock_req.call_args
            assert kwargs["headers"]["Authorization"] == "Bearer valid-access-token"
            assert kwargs["headers"]["Accept"] == "application/json"

            # Verify stored result request masked the Bearer token
            stored_headers = result["request"]["headers"]
            assert stored_headers["Authorization"] == "Bearer ********"

    def test_execute_test_injects_api_key_header(self):
        test_case = {
            "test_id": "TC-AUTH-2",
            "method": "POST",
            "endpoint": "/secure/data",
            "request": {"body": {"key": "value"}},
            "expected": {"status_code": 201}
        }

        auth_headers = {"X-API-KEY": "custom-api-key-value"}

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"created": True}

        with patch("requests.sessions.Session.request", return_value=mock_resp) as mock_req:
            result = execute_test(test_case, base_url="http://127.0.0.1:8000", auth_headers=auth_headers)

            assert result["actual"]["status_code"] == 201

            _, kwargs = mock_req.call_args
            assert kwargs["headers"]["X-API-KEY"] == "custom-api-key-value"

            # Result object masks the API key header
            assert result["request"]["headers"]["X-API-KEY"] == "********"


# ==========================================================
# 7. Endpoint Discovery with Authentication
# ==========================================================

class TestEndpointDiscovery:
    def test_discover_endpoints_with_auth(self):
        mock_project = {
            "id": 105,
            "user_id": 1,
            "project_name": "Petstore Secure",
            "base_url": "https://api.petstore.com",
            "openapi_url": "https://api.petstore.com/openapi.json",
            "auth_type": "bearer",
            "auth_secret_encrypted": encrypt_secret("petstore-jwt"),
            "has_credentials": True,
        }

        mock_openapi_data = {
            "openapi": "3.0.0",
            "paths": {
                "/pets": {
                    "get": {"summary": "List all pets"},
                    "post": {"summary": "Create pet", "requestBody": {}}
                }
            }
        }

        with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
             patch.object(proj_routes.db_operations, "get_project_by_id", return_value=mock_project), \
             patch("agent_backend.routes.projects.load_openapi", return_value=mock_openapi_data) as mock_load:

            resp = client.get("/projects/105/endpoints", headers={"Authorization": f"Bearer {TOKEN_A}"})

            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["project_id"] == 105
            assert data["total_endpoints"] == 2

            # Verify load_openapi was called with decrypted Bearer token
            _, kwargs = mock_load.call_args
            assert kwargs["auth_headers"] == {"Authorization": "Bearer petstore-jwt"}
