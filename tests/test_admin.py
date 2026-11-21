"""
Tests for Admin Endpoints, Role-Based Access Control, and Governance (Task 7).

Covers:
1. Default user role on registration is 'user'.
2. Public registration cannot create an admin user (role is forced to 'user').
3. Unauthenticated requests to /admin routes are rejected with 401.
4. Ordinary users (role='user') cannot access /admin routes (403 Forbidden).
5. Administrators (role='admin') can access /admin/overview, /admin/users, /admin/usage.
6. Admin user listing pagination and search work correctly.
7. Admin endpoints never expose password hashes or sensitive authentication data.
8. Individual user detail endpoint (/admin/users/{user_id}) returns profile and usage metrics.
"""

import sys
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup sys.path
REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi.testclient import TestClient

from agent_backend.app import app
import agent_backend.db_operations as db_ops
from agent_backend.auth import create_access_token

client = TestClient(app)

USER_ORDINARY = {
    "id": 1,
    "full_name": "Standard User",
    "email": "user@example.com",
    "role": "user",
    "plan": "internal_demo",
    "created_at": datetime(2026, 11, 1, 0, 0, 0),
}

USER_ADMIN = {
    "id": 99,
    "full_name": "Super Admin",
    "email": "admin@example.com",
    "role": "admin",
    "plan": "internal_demo",
    "created_at": datetime(2026, 10, 1, 0, 0, 0),
}

TOKEN_USER = create_access_token({"sub": "1", "email": "user@example.com", "name": "Standard User"})
TOKEN_ADMIN = create_access_token({"sub": "99", "email": "admin@example.com", "name": "Super Admin"})

AUTH_HEADER_USER = {"Authorization": f"Bearer {TOKEN_USER}"}
AUTH_HEADER_ADMIN = {"Authorization": f"Bearer {TOKEN_ADMIN}"}


# ===========================================================================
# 1. Registration Security & Default Role
# ===========================================================================

class TestRegistrationRoleSecurity:
    @patch("agent_backend.db_operations.get_user_by_email", return_value=None)
    @patch("agent_backend.db_operations.create_user")
    def test_default_role_on_registration_is_user(self, mock_create, mock_get_by_email):
        mock_create.return_value = {
            "id": 5,
            "full_name": "New User",
            "email": "new@example.com",
            "role": "user",
            "plan": "internal_demo",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        payload = {
            "full_name": "New User",
            "email": "new@example.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!"
        }
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 201
        data = resp.json()["data"]

        assert data["user"]["role"] == "user"
        assert mock_create.called
        kwargs = mock_create.call_args.kwargs if mock_create.call_args else {}
        assert kwargs.get("role") == "user"

    @patch("agent_backend.db_operations.get_user_by_email", return_value=None)
    @patch("agent_backend.db_operations.create_user")
    def test_public_registration_cannot_escalate_to_admin(self, mock_create, mock_get_by_email):
        mock_create.return_value = {
            "id": 6,
            "full_name": "Attacker",
            "email": "attacker@example.com",
            "role": "user",
            "plan": "internal_demo",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        # Attempt to pass role: admin in registration payload
        payload = {
            "full_name": "Attacker",
            "email": "attacker@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "role": "admin"
        }
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 201

        # Must be forced to role=user regardless of payload
        kwargs = mock_create.call_args.kwargs if mock_create.call_args else {}
        assert kwargs.get("role") == "user"


# ===========================================================================
# 2. Role-Based Access Control (RBAC)
# ===========================================================================

class TestRoleBasedAccessControl:
    def test_unauthenticated_admin_routes_rejected(self):
        assert client.get("/admin/overview").status_code == 401
        assert client.get("/admin/users").status_code == 401
        assert client.get("/admin/usage").status_code == 401
        assert client.get("/admin/users/1").status_code == 401

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ORDINARY)
    def test_ordinary_user_cannot_access_admin_overview(self, mock_get_user):
        resp = client.get("/admin/overview", headers=AUTH_HEADER_USER)
        assert resp.status_code == 403
        assert "Administrator access required" in resp.json()["detail"]

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ORDINARY)
    def test_ordinary_user_cannot_access_admin_users(self, mock_get_user):
        resp = client.get("/admin/users", headers=AUTH_HEADER_USER)
        assert resp.status_code == 403

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ORDINARY)
    def test_ordinary_user_cannot_access_admin_usage(self, mock_get_user):
        resp = client.get("/admin/usage", headers=AUTH_HEADER_USER)
        assert resp.status_code == 403


# ===========================================================================
# 3. Admin Overview and Governance Endpoints
# ===========================================================================

class TestAdminEndpoints:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ADMIN)
    @patch("agent_backend.routes.admin.get_db_connection")
    def test_admin_can_access_overview(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.side_effect = [
            {"total": 12},  # total users
            {"active_total": 8},  # active users
            {"total": 24},  # total projects
            {
                "total_runs": 100,
                "total_cases": 1000,
                "passed_cases": 950,
                "failed_cases": 50,
            },  # run stats
        ]
        mock_cursor.fetchall.side_effect = [
            [
                {
                    "id": 1,
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "role": "user",
                    "plan": "internal_demo",
                    "created_at": datetime(2026, 11, 19, 1, 0, 0),
                }
            ],  # recent registrations
            [
                {
                    "run_id": 42,
                    "user_id": 1,
                    "project_name": "Store API",
                    "total_tests": 10,
                    "passed_tests": 10,
                    "failed_tests": 0,
                    "created_at": datetime(2026, 11, 19, 1, 30, 0),
                    "status": "PASS",
                }
            ],  # recent activity
        ]

        resp = client.get("/admin/overview", headers=AUTH_HEADER_ADMIN)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_users"] == 12
        assert data["active_users"] == 8
        assert data["total_projects"] == 24
        assert data["total_test_runs"] == 100
        assert data["total_test_cases"] == 1000
        assert data["overall_pass_percentage"] == 95.0
        assert data["platform_mode"] in ("internal", "public")
        assert len(data["recent_registrations"]) == 1
        assert len(data["recent_activity"]) == 1

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ADMIN)
    @patch("agent_backend.routes.admin.get_db_connection")
    def test_admin_users_pagination_and_no_hash_exposure(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 50}
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "full_name": "Alice Developer",
                "email": "alice@example.com",
                "role": "user",
                "plan": "internal_demo",
                "created_at": datetime(2026, 11, 15, 12, 0, 0),
                "project_count": 3,
                "test_run_count": 15,
                "last_activity": datetime(2026, 11, 19, 8, 0, 0),
            }
        ]

        resp = client.get("/admin/users?limit=10&offset=0", headers=AUTH_HEADER_ADMIN)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 50
        assert len(data["items"]) == 1
        user_row = data["items"][0]
        assert user_row["email"] == "alice@example.com"
        assert user_row["project_count"] == 3

        # Must NEVER expose password hashes
        assert "password" not in str(data)
        assert "password_hash" not in str(data)

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ADMIN)
    @patch("agent_backend.routes.admin.get_db_connection")
    def test_admin_user_detail_view(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.side_effect = [
            {
                "id": 10,
                "full_name": "Bob Target",
                "email": "bob@example.com",
                "role": "user",
                "plan": "pro",
                "created_at": datetime(2026, 11, 10, 0, 0, 0),
                "updated_at": datetime(2026, 11, 10, 0, 0, 0),
            },
            {
                "total_runs": 8,
                "total_tests": 80,
                "passed_tests": 76,
                "failed_tests": 4,
                "last_activity": datetime(2026, 11, 18, 14, 0, 0),
            }
        ]
        mock_cursor.fetchall.return_value = [
            {
                "id": 101,
                "project_name": "Inventory API",
                "base_url": "https://inv.example.com",
                "auth_type": "bearer",
                "created_at": datetime(2026, 11, 11, 0, 0, 0),
                "run_count": 8,
            }
        ]

        resp = client.get("/admin/users/10", headers=AUTH_HEADER_ADMIN)
        assert resp.status_code == 200
        data = resp.json()

        assert data["user"]["email"] == "bob@example.com"
        assert data["usage"]["total_runs"] == 8
        assert data["usage"]["pass_percentage"] == 95.0
        assert len(data["projects"]) == 1
        assert data["projects"][0]["project_name"] == "Inventory API"

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ADMIN)
    @patch("agent_backend.routes.admin.get_db_connection")
    def test_admin_usage_telemetry(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchall.return_value = [
            {"plan": "internal_demo", "user_count": 15},
            {"plan": "pro", "user_count": 3}
        ]
        mock_cursor.fetchone.side_effect = [
            {"total_projects": 30},
            {
                "total_runs": 250,
                "total_cases": 2500,
                "passed_cases": 2400,
                "failed_cases": 100,
            },
            {"total_ai_operations": 120}
        ]

        resp = client.get("/admin/usage", headers=AUTH_HEADER_ADMIN)
        assert resp.status_code == 200
        data = resp.json()

        assert data["plan_distribution"]["internal_demo"] == 15
        assert data["plan_distribution"]["pro"] == 3
        assert data["total_projects"] == 30
        assert data["total_test_runs"] == 250
        assert data["total_ai_operations"] == 120
        assert "available_plans" in data


# ===========================================================================
# 8. Stale JWT & Demotion Verification (Fix 7 Audit Check)
# ===========================================================================

class TestAdminDemotionAndStaleToken:
    @patch("agent_backend.db_operations.get_user_by_id")
    def test_demoted_admin_with_valid_jwt_is_immediately_rejected(self, mock_get_user):
        """
        If a user was an admin when their JWT was issued, but their database
        role has since been updated to 'user', subsequent requests using that
        token must be rejected with 403 Forbidden because get_current_admin_user
        checks the live database record, not just JWT claims.
        """
        # User in DB is now 'user'
        mock_get_user.return_value = {
            "id": 99,
            "full_name": "Former Admin",
            "email": "admin@example.com",
            "role": "user",
            "plan": "internal_demo",
            "created_at": datetime(2026, 10, 1, 0, 0, 0),
        }

        # Request made using TOKEN_ADMIN
        resp = client.get("/admin/overview", headers=AUTH_HEADER_ADMIN)
        assert resp.status_code == 403
        assert "Administrator access required" in resp.json().get("detail", "")


# ===========================================================================
# 9. CLI Administration Tool (promote_admin.py)
# ===========================================================================

class TestAdminCLITool:
    @patch("agent_backend.promote_admin.get_user_by_email")
    @patch("agent_backend.promote_admin.get_db_connection")
    def test_promote_and_demote_functions(self, mock_get_conn, mock_get_user):
        import agent_backend.promote_admin as cli

        mock_get_user.return_value = {
            "id": 42,
            "full_name": "Alice Developer",
            "email": "alice@example.com",
            "role": "user",
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Test promote
        res_promote = cli.promote_user_to_admin("alice@example.com")
        assert res_promote is True
        mock_cursor.execute.assert_called_with(
            "UPDATE users SET role = %s WHERE id = %s", ("admin", 42)
        )

        # Test demote
        res_demote = cli.demote_admin_to_user("alice@example.com")
        assert res_demote is True
        mock_cursor.execute.assert_called_with(
            "UPDATE users SET role = %s WHERE id = %s", ("user", 42)
        )

    @patch("agent_backend.promote_admin.get_user_by_email")
    @patch("agent_backend.promote_admin.get_db_connection")
    def test_assign_user_plan_valid_and_invalid(self, mock_get_conn, mock_get_user):
        import agent_backend.promote_admin as cli

        mock_get_user.return_value = {
            "id": 42,
            "full_name": "Alice Developer",
            "email": "alice@example.com",
            "role": "user",
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Valid plan
        res_valid = cli.assign_user_plan("alice@example.com", "pro")
        assert res_valid is True
        mock_cursor.execute.assert_called_with(
            "UPDATE users SET plan = %s WHERE id = %s", ("pro", 42)
        )

        # Invalid plan
        res_invalid = cli.assign_user_plan("alice@example.com", "super_unlimited_vip")
        assert res_invalid is False

    @patch("agent_backend.promote_admin.get_user_by_email", return_value=None)
    def test_cli_nonexistent_user(self, mock_get_user):
        import agent_backend.promote_admin as cli

        res = cli.set_user_role("ghost@example.com", "admin")
        assert res is False
        res_plan = cli.assign_user_plan("ghost@example.com", "pro")
        assert res_plan is False
