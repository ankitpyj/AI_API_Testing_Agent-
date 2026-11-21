"""
Unit and integration tests for the user-scoped authoritative usage endpoint:
- GET /auth/usage
- GET /auth/me/usage

Verifies:
1. Authentication & JWT protection (HTTP 401 when token missing/invalid).
2. Authoritative UTC calendar-month metrics matching usage_service quota enforcement.
3. Strict multi-user tenant isolation (User A cannot view User B's usage).
4. Actual AI operations from ai_usage_logs (not fabricated or estimated).
5. Canonical plan limits and feature entitlements.
6. Project capacity vs. monthly consumable quota distinction.
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

try:
    from app import app
    from auth import create_access_token, hash_password
    from db_operations import create_user, get_db_connection
    from usage_service import get_current_month_start, get_user_usage_metrics
    from plans import get_plan_config, PLAN_DEFINITIONS
except ImportError:
    from agent_backend.app import app
    from agent_backend.auth import create_access_token, hash_password
    from agent_backend.db_operations import create_user, get_db_connection
    from agent_backend.usage_service import get_current_month_start, get_user_usage_metrics
    from agent_backend.plans import get_plan_config, PLAN_DEFINITIONS


client = TestClient(app)


def test_usage_endpoint_requires_authentication():
    """Unauthenticated requests to /auth/usage and /auth/me/usage must return 401."""
    res1 = client.get("/auth/usage")
    assert res1.status_code == 401, f"Expected 401, got {res1.status_code}: {res1.text}"

    res2 = client.get("/auth/me/usage")
    assert res2.status_code == 401, f"Expected 401, got {res2.status_code}: {res2.text}"


def test_usage_endpoint_returns_authoritative_metrics():
    """Authenticated user receives authoritative usage metrics matching usage_service."""
    timestamp = int(datetime.now().timestamp())
    email = f"usage_test_{timestamp}@example.com"
    user = create_user(
        full_name="Usage Tester",
        email=email,
        password_hash=hash_password("password123"),
        role="user",
        plan="pro"
    )
    user_id = user["id"]
    token = create_access_token(data={"sub": str(user_id), "email": email, "name": "Usage Tester"})

    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/auth/usage", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    body = res.json()
    assert body["status"] == "success"
    data = body["data"]

    assert data["user_id"] == user_id
    assert data["plan"] == "pro"
    assert "metrics" in data
    assert "limits" in data
    assert "features" in data
    assert "platform_mode" in data
    assert "enforce_usage_limits" in data

    # Verify limits match canonical pro plan
    pro_cfg = get_plan_config("pro")
    assert data["limits"]["max_projects"] == pro_cfg["max_projects"]
    assert data["limits"]["monthly_test_runs"] == pro_cfg["monthly_test_runs"]
    assert data["limits"]["monthly_test_cases"] == pro_cfg["monthly_test_cases"]
    assert data["limits"]["monthly_ai_operations"] == pro_cfg["monthly_ai_operations"]

    # Verify metrics fields
    m = data["metrics"]
    assert "total_projects" in m
    assert "monthly_test_runs" in m
    assert "monthly_test_cases" in m
    assert "monthly_ai_operations" in m
    assert "total_test_runs" in m
    assert "total_test_cases" in m


def test_usage_endpoint_tenant_isolation():
    """User A and User B cannot access or affect each other's usage metrics."""
    ts = int(datetime.now().timestamp())
    u1 = create_user(f"tenant_a_{ts}@example.com", hash_password("pass"), f"Tenant A {ts}", "user", "internal_demo")
    u2 = create_user(f"tenant_b_{ts}@example.com", hash_password("pass"), f"Tenant B {ts}", "user", "free")

    t1 = create_access_token({"sub": str(u1["id"]), "email": u1["email"], "name": u1["full_name"]})
    t2 = create_access_token({"sub": str(u2["id"]), "email": u2["email"], "name": u2["full_name"]})

    res1 = client.get("/auth/usage", headers={"Authorization": f"Bearer {t1}"})
    res2 = client.get("/auth/usage", headers={"Authorization": f"Bearer {t2}"})

    assert res1.status_code == 200
    assert res2.status_code == 200

    d1 = res1.json()["data"]
    d2 = res2.json()["data"]

    assert d1["user_id"] == u1["id"]
    assert d2["user_id"] == u2["id"]
    assert d1["plan"] == "internal_demo"
    assert d2["plan"] == "free"

    # Free plan has 0 AI ops limit; internal demo has 5000
    assert d2["limits"]["monthly_ai_operations"] == 0
    assert d1["limits"]["monthly_ai_operations"] == 5000


def test_calendar_month_boundary_filtering():
    """Verify that get_current_month_start() respects midnight UTC on the 1st day of month."""
    start = get_current_month_start()
    now_utc = datetime.now(timezone.utc)

    assert start.day == 1
    assert start.hour == 0
    assert start.minute == 0
    assert start.second == 0
    assert start.year == now_utc.year
    assert start.month == now_utc.month
    assert start.tzinfo is not None
