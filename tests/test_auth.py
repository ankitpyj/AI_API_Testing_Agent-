import sys
import os
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

# Setup sys.path to ensure agent_backend can be imported regardless of execution working directory
REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi.testclient import TestClient

from agent_backend.app import app
from agent_backend.routes import auth as auth_routes
from agent_backend import auth as auth_module
from agent_backend.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)
import jwt


client = TestClient(app)


# ==========================================
# 1. Password Hashing & Verification Tests
# ==========================================

def test_password_hashing_and_verification():
    raw_password = "SuperSecretPassword123!"
    hashed = hash_password(raw_password)

    # Must be hashed and not equal to plaintext
    assert hashed != raw_password
    assert hashed.startswith("$2b$")

    # Correct password verifies
    assert verify_password(raw_password, hashed) is True

    # Wrong password fails verification
    assert verify_password("WrongPassword123!", hashed) is False

    # Edge cases
    assert verify_password("", hashed) is False
    assert verify_password(raw_password, "") is False
    assert verify_password(raw_password, "invalid_hash_format") is False


def test_hash_empty_password_raises_error():
    with pytest.raises(ValueError):
        hash_password("")


# ==========================================
# 2. JWT Generation & Verification Tests
# ==========================================

def test_jwt_create_and_decode_valid_token():
    payload = {"sub": "42", "email": "test@example.com", "name": "Test User"}
    token = create_access_token(payload)

    assert isinstance(token, str)
    decoded = decode_access_token(token)

    assert decoded["sub"] == "42"
    assert decoded["email"] == "test@example.com"
    assert decoded["name"] == "Test User"
    assert "exp" in decoded
    assert "iat" in decoded


def test_jwt_expired_token():
    payload = {"sub": "42", "email": "test@example.com"}
    # Token expired 10 minutes ago
    expired_token = create_access_token(payload, expires_delta=timedelta(minutes=-10))

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_jwt_invalid_token():
    with pytest.raises(jwt.PyJWTError):
        decode_access_token("not.a.valid.jwt.token")


# ==========================================
# 3. Registration Tests
# ==========================================

def test_register_success():
    mock_user = {
        "id": 1,
        "full_name": "Alice Tester",
        "email": "alice@example.com",
        "created_at": "2026-11-18 12:00:00",
        "updated_at": "2026-11-18 12:00:00"
    }

    with patch.object(auth_routes.db_operations, "get_user_by_email", return_value=None), \
         patch.object(auth_routes.db_operations, "create_user", return_value=mock_user):

        response = client.post("/auth/register", json={
            "full_name": "Alice Tester",
            "email": "alice@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["user"]["id"] == 1
        assert data["data"]["user"]["email"] == "alice@example.com"
        assert data["data"]["user"]["full_name"] == "Alice Tester"


def test_register_duplicate_email():
    existing_user = {
        "id": 1,
        "full_name": "Existing User",
        "email": "alice@example.com",
        "password_hash": "$2b$12$somehash..."
    }

    with patch.object(auth_routes.db_operations, "get_user_by_email", return_value=existing_user):
        response = client.post("/auth/register", json={
            "full_name": "Alice Tester",
            "email": "alice@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })

        assert response.status_code == 400
        assert response.json()["detail"] == "Email is already registered"


def test_register_password_mismatch():
    response = client.post("/auth/register", json={
        "full_name": "Alice Tester",
        "email": "alice@example.com",
        "password": "Password123!",
        "confirm_password": "DifferentPassword123!"
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "Passwords do not match"


def test_register_short_password():
    response = client.post("/auth/register", json={
        "full_name": "Alice Tester",
        "email": "alice@example.com",
        "password": "short",
        "confirm_password": "short"
    })

    assert response.status_code == 422


def test_register_invalid_email():
    response = client.post("/auth/register", json={
        "full_name": "Alice Tester",
        "email": "not-an-email",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })

    assert response.status_code == 422


# ==========================================
# 4. Login Tests
# ==========================================

def test_login_success():
    hashed = hash_password("CorrectPassword123!")
    user_record = {
        "id": 1,
        "full_name": "Bob Tester",
        "email": "bob@example.com",
        "password_hash": hashed,
        "created_at": "2026-11-18 12:00:00",
        "updated_at": "2026-11-18 12:00:00"
    }

    with patch.object(auth_routes.db_operations, "get_user_by_email", return_value=user_record):
        response = client.post("/auth/login", json={
            "email": "bob@example.com",
            "password": "CorrectPassword123!"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["user"]["id"] == 1
        assert "password_hash" not in data["data"]["user"]


def test_login_invalid_password():
    hashed = hash_password("CorrectPassword123!")
    user_record = {
        "id": 1,
        "full_name": "Bob Tester",
        "email": "bob@example.com",
        "password_hash": hashed
    }

    with patch.object(auth_routes.db_operations, "get_user_by_email", return_value=user_record):
        response = client.post("/auth/login", json={
            "email": "bob@example.com",
            "password": "WrongPassword!"
        })

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"


def test_login_nonexistent_user():
    with patch.object(auth_routes.db_operations, "get_user_by_email", return_value=None):
        response = client.post("/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "Password123!"
        })

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"


# ==========================================
# 5. Authenticated Profile (GET /auth/me) Tests
# ==========================================

def test_get_me_success():
    valid_token = create_access_token({"sub": "1", "email": "carol@example.com"})
    user_record = {
        "id": 1,
        "full_name": "Carol Tester",
        "email": "carol@example.com",
        "password_hash": "$2b$12$...",
        "created_at": "2026-11-18 12:00:00",
        "updated_at": "2026-11-18 12:00:00"
    }

    with patch.object(auth_module.db_operations, "get_user_by_id", return_value=user_record):
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {valid_token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["id"] == 1
        assert data["data"]["email"] == "carol@example.com"
        assert "password_hash" not in data["data"]


def test_get_me_missing_token():
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication credentials were not provided"


def test_get_me_invalid_token():
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication token"


def test_get_me_expired_token():
    expired_token = create_access_token({"sub": "1"}, expires_delta=timedelta(minutes=-5))
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


def test_get_me_user_not_found():
    valid_token = create_access_token({"sub": "9999", "email": "ghost@example.com"})
    with patch.object(auth_module.db_operations, "get_user_by_id", return_value=None):
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
        assert response.status_code == 401
        assert response.json()["detail"] == "User not found"


# ==========================================
# 6. Logout Endpoint Tests
# ==========================================

def test_logout_endpoint():
    response = client.post("/auth/logout")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "discard its token" in data["message"]
