import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup sys.path to ensure agent_backend can be imported regardless of execution working directory
REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi.testclient import TestClient

from agent_backend.app import app
import agent_backend.db_operations as db_ops
from agent_backend.routes import projects as proj_routes
from agent_backend.auth import create_access_token

client = TestClient(app)

# Mock users
USER_A = {"id": 1, "full_name": "User Alpha", "email": "alpha@example.com"}
USER_B = {"id": 2, "full_name": "User Beta", "email": "beta@example.com"}

TOKEN_A = create_access_token({"sub": "1", "email": "alpha@example.com", "name": "User Alpha"})
TOKEN_B = create_access_token({"sub": "2", "email": "beta@example.com", "name": "User Beta"})


# ==========================================================
# 1. Unauthenticated Project Access Rejected
# ==========================================================

def test_unauthenticated_project_endpoints_rejected():
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json={"project_name": "Test", "base_url": "http://127.0.0.1:8000"}).status_code == 401
    assert client.get("/projects/1").status_code == 401
    assert client.put("/projects/1", json={"project_name": "Test", "base_url": "http://127.0.0.1:8000"}).status_code == 401
    assert client.delete("/projects/1").status_code == 401


# ==========================================================
# 2. User A Creates and Lists Own Projects
# ==========================================================

def test_user_a_create_and_list_projects():
    created_proj = {
        "id": 10,
        "user_id": 1,
        "project_name": "E-commerce API",
        "description": "Store backend",
        "base_url": "https://api.ecommerce.com",
        "openapi_url": "https://api.ecommerce.com/openapi.json",
        "created_at": "2026-11-19 00:00:00",
        "updated_at": "2026-11-19 00:00:00"
    }

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch.object(proj_routes.db_operations, "create_project", return_value=created_proj) as mock_create, \
         patch.object(proj_routes.db_operations, "get_projects_by_user", return_value=[created_proj]) as mock_get_user_projs:

        # 1. Create project
        resp = client.post(
            "/projects",
            json={
                "project_name": "E-commerce API",
                "description": "Store backend",
                "base_url": "https://api.ecommerce.com",
                "openapi_url": "https://api.ecommerce.com/openapi.json"
            },
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["id"] == 10
        assert data["project_name"] == "E-commerce API"
        mock_create.assert_called_once_with(
            user_id=1,
            project_name="E-commerce API",
            base_url="https://api.ecommerce.com",
            openapi_url="https://api.ecommerce.com/openapi.json",
            description="Store backend"
        )

        # 2. List projects
        resp_list = client.get("/projects", headers={"Authorization": f"Bearer {TOKEN_A}"})
        assert resp_list.status_code == 200
        projs = resp_list.json()["data"]
        assert len(projs) == 1
        assert projs[0]["project_name"] == "E-commerce API"
        mock_get_user_projs.assert_called_once_with(user_id=1)


# ==========================================================
# 3. URL Validation Enforcement
# ==========================================================

def test_invalid_urls_rejected():
    with patch.object(db_ops, "get_user_by_id", return_value=USER_A):
        # Missing scheme / invalid format
        resp = client.post(
            "/projects",
            json={
                "project_name": "Invalid API",
                "base_url": "not-a-valid-url"
            },
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp.status_code == 422


# ==========================================================
# 4. User B Cannot Access, Update or Delete User A's Project
# ==========================================================

def test_user_b_cannot_access_user_a_project():
    proj_a = {
        "id": 10,
        "user_id": 1,
        "project_name": "E-commerce API",
        "base_url": "https://api.ecommerce.com"
    }

    with patch.object(db_ops, "get_user_by_id", return_value=USER_B), \
         patch.object(proj_routes.db_operations, "get_project_by_id", return_value=proj_a), \
         patch.object(proj_routes.db_operations, "update_project", return_value=None), \
         patch.object(proj_routes.db_operations, "delete_project", return_value=False):

        # 1. User B tries to GET User A's project
        resp_get = client.get("/projects/10", headers={"Authorization": f"Bearer {TOKEN_B}"})
        assert resp_get.status_code == 404
        assert resp_get.json()["detail"] == "Project not found"

        # 2. User B tries to PUT User A's project
        resp_put = client.put(
            "/projects/10",
            json={
                "project_name": "Hacked Project",
                "base_url": "https://hacked.com"
            },
            headers={"Authorization": f"Bearer {TOKEN_B}"}
        )
        assert resp_put.status_code == 404
        assert resp_put.json()["detail"] == "Project not found"

        # 3. User B tries to DELETE User A's project
        resp_del = client.delete("/projects/10", headers={"Authorization": f"Bearer {TOKEN_B}"})
        assert resp_del.status_code == 404
        assert resp_del.json()["detail"] == "Project not found"


# ==========================================================
# 5. User A Can Update and Delete Own Project
# ==========================================================

def test_user_a_can_update_and_delete_own_project():
    updated_proj = {
        "id": 10,
        "user_id": 1,
        "project_name": "E-commerce API v2",
        "base_url": "https://api.v2.ecommerce.com",
        "openapi_url": None,
        "description": "Updated"
    }

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch.object(proj_routes.db_operations, "update_project", return_value=updated_proj) as mock_update, \
         patch.object(proj_routes.db_operations, "delete_project", return_value=True) as mock_delete:

        # Update
        resp_put = client.put(
            "/projects/10",
            json={
                "project_name": "E-commerce API v2",
                "base_url": "https://api.v2.ecommerce.com",
                "description": "Updated"
            },
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp_put.status_code == 200
        assert resp_put.json()["data"]["project_name"] == "E-commerce API v2"

        # Delete
        resp_del = client.delete("/projects/10", headers={"Authorization": f"Bearer {TOKEN_A}"})
        assert resp_del.status_code == 200
        assert resp_del.json()["message"] == "Project deleted successfully"


# ==========================================================
# 6. Project Testing Integration & Ownership Enforcement
# ==========================================================

def test_run_tests_with_valid_project():
    proj_a = {
        "id": 10,
        "user_id": 1,
        "project_name": "E-commerce API",
        "base_url": "https://api.ecommerce.com",
        "openapi_url": "https://api.ecommerce.com/openapi.json"
    }
    mock_run_result = {"total_tests": 5, "passed": 5, "failed": 0, "results": []}

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch.object(db_ops, "get_project_by_id", return_value=proj_a), \
         patch("agent_backend.app.run_all_tests", return_value=mock_run_result) as mock_run:

        resp = client.post(
            "/run-tests",
            json={"project_id": 10},
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp.status_code == 200
        mock_run.assert_called_once_with(
            base_url="https://api.ecommerce.com",
            openapi_url="https://api.ecommerce.com/openapi.json",
            user_id=1,
            project_id=10
        )


def test_user_b_cannot_run_tests_with_user_a_project():
    proj_a = {
        "id": 10,
        "user_id": 1,
        "project_name": "E-commerce API",
        "base_url": "https://api.ecommerce.com"
    }

    with patch.object(db_ops, "get_user_by_id", return_value=USER_B), \
         patch.object(db_ops, "get_project_by_id", return_value=proj_a):

        # User B attempts to run tests against User A's project
        resp = client.post(
            "/run-tests",
            json={"project_id": 10},
            headers={"Authorization": f"Bearer {TOKEN_B}"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"
