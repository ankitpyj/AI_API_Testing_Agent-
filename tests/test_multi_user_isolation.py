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
from agent_backend.auth import create_access_token

client = TestClient(app)


# Mock users
USER_A = {"id": 1, "full_name": "User Alpha", "email": "alpha@example.com"}
USER_B = {"id": 2, "full_name": "User Beta", "email": "beta@example.com"}

TOKEN_A = create_access_token({"sub": "1", "email": "alpha@example.com", "name": "User Alpha"})
TOKEN_B = create_access_token({"sub": "2", "email": "beta@example.com", "name": "User Beta"})


# ==========================================================
# 1. Unauthenticated Access Rejection Tests
# ==========================================================

def test_unauthenticated_run_tests_rejected():
    response = client.post("/run-tests", json={"base_url": "http://127.0.0.1:8000"})
    assert response.status_code == 401
    assert "detail" in response.json()


def test_unauthenticated_get_test_runs_rejected():
    response = client.get("/test-runs")
    assert response.status_code == 401


def test_unauthenticated_get_results_rejected():
    response = client.get("/test-runs/1/results")
    assert response.status_code == 401


def test_unauthenticated_get_bugs_rejected():
    response = client.get("/test-runs/1/bugs")
    assert response.status_code == 401


# ==========================================================
# 2. User A Creates & Views Own Test Runs
# ==========================================================

def test_user_a_can_create_and_view_own_runs():
    mock_run_result = {
        "total_tests": 10,
        "passed": 9,
        "failed": 1,
        "results": []
    }

    user_a_runs = [
        {"id": 101, "user_id": 1, "total_tests": 10, "passed_tests": 9, "failed_tests": 1}
    ]

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch("agent_backend.app.run_all_tests", return_value=mock_run_result) as mock_run_all, \
         patch.object(db_ops, "get_test_runs", return_value=user_a_runs) as mock_get_runs:

        # 1. Run tests as User A
        response = client.post(
            "/run-tests",
            json={"base_url": "http://127.0.0.1:8000"},
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify user_id=1 was passed to run_all_tests
        mock_run_all.assert_called_once()
        _, kwargs = mock_run_all.call_args
        assert kwargs.get("user_id") == 1

        # 2. View runs as User A
        response_runs = client.get("/test-runs", headers={"Authorization": f"Bearer {TOKEN_A}"})
        assert response_runs.status_code == 200
        runs_data = response_runs.json()["data"]
        assert len(runs_data) == 1
        assert runs_data[0]["user_id"] == 1
        mock_get_runs.assert_called_once_with(user_id=1)


# ==========================================================
# 3. User B Cannot View User A's Test Runs
# ==========================================================

def test_user_b_gets_only_their_own_runs():
    user_b_runs = [
        {"id": 201, "user_id": 2, "total_tests": 5, "passed_tests": 5, "failed_tests": 0}
    ]

    with patch.object(db_ops, "get_user_by_id", return_value=USER_B), \
         patch.object(db_ops, "get_test_runs", return_value=user_b_runs) as mock_get_runs:

        response = client.get("/test-runs", headers={"Authorization": f"Bearer {TOKEN_B}"})
        assert response.status_code == 200
        runs = response.json()["data"]
        assert len(runs) == 1
        assert runs[0]["user_id"] == 2
        mock_get_runs.assert_called_once_with(user_id=2)


# ==========================================================
# 4. User B Cannot Access User A's Results or Bug Reports
# ==========================================================

def test_user_b_cannot_access_user_a_results_or_bugs():
    # Run 101 belongs to User A (user_id = 1)
    run_101 = {"id": 101, "user_id": 1, "total_tests": 10}

    with patch.object(db_ops, "get_user_by_id", return_value=USER_B), \
         patch.object(db_ops, "get_test_run_by_id", return_value=run_101):

        # User B attempts to access User A's results
        resp_results = client.get(
            "/test-runs/101/results",
            headers={"Authorization": f"Bearer {TOKEN_B}"}
        )
        assert resp_results.status_code == 404
        assert resp_results.json()["detail"] == "Test run not found"

        # User B attempts to access User A's bugs
        resp_bugs = client.get(
            "/test-runs/101/bugs",
            headers={"Authorization": f"Bearer {TOKEN_B}"}
        )
        assert resp_bugs.status_code == 404
        assert resp_bugs.json()["detail"] == "Test run not found"


# ==========================================================
# 5. User A Can Access Own Results & Bugs
# ==========================================================

def test_user_a_can_access_own_results_and_bugs():
    run_101 = {"id": 101, "user_id": 1, "total_tests": 10}
    mock_results = [{"id": 1, "run_id": 101, "status": "PASS"}]
    mock_bugs = [{"id": 1, "run_id": 101, "severity": "high"}]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch.object(db_ops, "get_test_run_by_id", return_value=run_101), \
         patch("agent_backend.app.get_db_connection", return_value=mock_conn):

        mock_cursor.fetchall.return_value = mock_results
        resp_results = client.get(
            "/test-runs/101/results",
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp_results.status_code == 200
        assert resp_results.json()["data"] == mock_results

        mock_cursor.fetchall.return_value = mock_bugs
        resp_bugs = client.get(
            "/test-runs/101/bugs",
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp_bugs.status_code == 200
        assert resp_bugs.json()["data"] == mock_bugs


# ==========================================================
# 6. Historical Unowned (NULL user_id) Run Protection
# ==========================================================

def test_unowned_historical_run_inaccessible_by_arbitrary_user():
    # Historical record before migration: user_id is None
    unowned_run = {"id": 5, "user_id": None, "total_tests": 10}

    with patch.object(db_ops, "get_user_by_id", return_value=USER_A), \
         patch.object(db_ops, "get_test_run_by_id", return_value=unowned_run):

        resp = client.get(
            "/test-runs/5/results",
            headers={"Authorization": f"Bearer {TOKEN_A}"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Test run not found"
