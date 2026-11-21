"""
Production Monitoring, Correlation ID, and Health Check Test Suite for Task 10.
"""

import os
import json
import uuid
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["ENABLE_BACKGROUND_WORKER"] = "false"

from agent_backend.app import app
from agent_backend.auth import create_access_token
from agent_backend.database import get_db_connection
from agent_backend.logger import JSONFormatter, logger, request_id_ctx


def can_connect_to_mysql():
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not can_connect_to_mysql(),
    reason="MySQL database is not reachable. Requires active Aiven MySQL connection."
)


def test_correlation_id_generated_and_returned():
    """Verify that every request without X-Request-ID receives a newly generated UUID in response header."""
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    req_id = response.headers.get("X-Request-ID")
    assert req_id is not None
    assert len(req_id) >= 16


def test_correlation_id_preserved_when_supplied():
    """Verify that a client-supplied X-Request-ID is preserved and echoed back in the response header."""
    client = TestClient(app)
    custom_trace = f"trace-{uuid.uuid4().hex}"
    response = client.get("/health/live", headers={"X-Request-ID": custom_trace})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_trace


def test_health_live_endpoint():
    """Verify liveness probe returns 200 OK and alive status."""
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "timestamp" in data
    assert data["service"] == "ai-api-testing-backend"


def test_health_ready_endpoint():
    """Verify readiness probe checks database connectivity and worker slots."""
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "connected"
    assert isinstance(data["checks"]["worker_slots"], int)
    assert data["checks"]["worker_slots"] >= 1


def test_health_ready_unhealthy_when_db_down():
    """Verify readiness probe returns 503 Service Unavailable when DB is disconnected."""
    client = TestClient(app)
    with patch("agent_backend.app.get_db_connection", side_effect=Exception("Database unreachable")):
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()["detail"]
        assert data["status"] == "not_ready"
        assert "error" in data["checks"]["database"]


def test_structured_json_logger_formatting():
    """Verify JSONFormatter produces valid, parseable JSON with required operational fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Worker claimed job %d successfully",
        args=(101,),
        exc_info=None
    )
    request_id_ctx.set("corr-abc-123")
    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Worker claimed job 101 successfully"
    assert parsed["request_id"] == "corr-abc-123"
    assert "timestamp" in parsed
    assert parsed["line"] == 42


def test_admin_worker_metrics_endpoint():
    """Verify /admin/worker-metrics returns queue depth and slot utilization for admins, 403 for others."""
    client = TestClient(app)

    admin_user = {"id": 9999, "role": "admin", "email": "admin@test.com", "plan": "enterprise"}
    ordinary_user = {"id": 8888, "role": "user", "email": "user@test.com", "plan": "pro"}

    admin_token = create_access_token({"sub": "9999", "id": 9999, "role": "admin", "plan": "enterprise"})
    user_token = create_access_token({"sub": "8888", "id": 8888, "role": "user", "plan": "pro"})

    # 1. Admin user has access
    with patch("agent_backend.db_operations.get_user_by_id", return_value=admin_user):
        resp = client.get("/admin/worker-metrics", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        metrics = resp.json()

        assert "slots" in metrics
        assert "queue" in metrics
        assert "recent_24h" in metrics
        assert metrics["slots"]["total"] >= 1
        assert isinstance(metrics["queue"]["depth"], int)
        assert isinstance(metrics["queue"]["running"], int)
        assert "timestamp" in metrics

    # 2. Non-admin regular user is rejected with 403
    with patch("agent_backend.db_operations.get_user_by_id", return_value=ordinary_user):
        unauth_resp = client.get("/admin/worker-metrics", headers={"Authorization": f"Bearer {user_token}"})
        assert unauth_resp.status_code == 403
