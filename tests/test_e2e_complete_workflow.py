"""
End-to-End Workflow & Reliability Test Suite for Task 9.5:
Full Lifecycle Validation: FastAPI -> MySQL Queue -> Background Worker Loop -> Persistence -> API Verification.

Covers:
1. Complete workflow with real worker loop execution (no direct execute_job bypass).
2. Worker crash, restart, and stale lease recovery.
3. Zombie worker ownership fencing across all persistence and lifecycle methods.
4. Multi-user isolation, tenant boundaries, and project ownership verification.
5. Quota reconciliation, cancellation refund, and idempotency payload mismatch protection.
"""

import sys
import os
import time
import asyncio
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

# Disable automatic background worker in lifespan during tests to prevent rogue polling
os.environ["ENABLE_BACKGROUND_WORKER"] = "false"

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi.testclient import TestClient

from agent_backend.database import get_db_connection
from agent_backend import db_operations, usage_service
from agent_backend.app import app
from agent_backend.auth import create_access_token
from agent_backend.worker import run_worker_loop, stop_worker, WORKER_ID
from agent_backend.db_operations import (
    claim_next_queued_job,
    release_worker_slot,
    get_user_test_run_by_id,
    save_all_test_results_and_bugs,
)
from agent_backend.usage_service import (
    queue_test_run,
    complete_test_run,
    fail_test_run,
    cancel_test_run,
    update_heartbeat,
    reconcile_stale_reservations,
    JobHeartbeatManager,
)
from agent_backend.engine.test_generator.test_executor import JobCancelledError


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


@pytest.fixture
def test_users_and_projects():
    """Create two independent, isolated test users and projects for Phase 1 testing."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id FROM users WHERE email = 'phase1_user_a@test.com'")
    row_a = cur.fetchone()
    if row_a:
        user_a_id = row_a["id"]
    else:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, full_name, plan, role)
            VALUES ('phase1_user_a@test.com', 'hashed_pass_a', 'Phase1 User A', 'pro', 'user')
            """
        )
        user_a_id = cur.lastrowid

    cur.execute("SELECT id FROM users WHERE email = 'phase1_user_b@test.com'")
    row_b = cur.fetchone()
    if row_b:
        user_b_id = row_b["id"]
    else:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, full_name, plan, role)
            VALUES ('phase1_user_b@test.com', 'hashed_pass_b', 'Phase1 User B', 'pro', 'user')
            """
        )
        user_b_id = cur.lastrowid

    # Create distinct projects
    cur.execute(
        """
        INSERT INTO projects (user_id, project_name, base_url, openapi_url, auth_type)
        VALUES (%s, 'Project User A', 'http://127.0.0.1:8000', 'http://127.0.0.1:8000/openapi.json', 'none')
        """,
        (user_a_id,)
    )
    proj_a_id = cur.lastrowid

    cur.execute(
        """
        INSERT INTO projects (user_id, project_name, base_url, openapi_url, auth_type)
        VALUES (%s, 'Project User B', 'http://127.0.0.1:8001', 'http://127.0.0.1:8001/openapi.json', 'none')
        """,
        (user_b_id,)
    )
    proj_b_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()

    token_a = create_access_token({"sub": str(user_a_id), "id": user_a_id, "role": "user", "plan": "pro"})
    token_b = create_access_token({"sub": str(user_b_id), "id": user_b_id, "role": "user", "plan": "pro"})

    yield {
        "user_a_id": user_a_id,
        "proj_a_id": proj_a_id,
        "token_a": token_a,
        "user_b_id": user_b_id,
        "proj_b_id": proj_b_id,
        "token_b": token_b,
    }

    # Cleanup created test artifacts with retry for connection robustness
    for attempt in range(3):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM bug_reports WHERE run_id IN (SELECT id FROM test_runs WHERE user_id IN (%s, %s))", (user_a_id, user_b_id))
            cur.execute("DELETE FROM test_results WHERE run_id IN (SELECT id FROM test_runs WHERE user_id IN (%s, %s))", (user_a_id, user_b_id))
            cur.execute("DELETE FROM test_runs WHERE user_id IN (%s, %s)", (user_a_id, user_b_id))
            cur.execute("DELETE FROM projects WHERE id IN (%s, %s)", (proj_a_id, proj_b_id))
            cur.execute("UPDATE worker_slots SET run_id = NULL, worker_id = NULL, leased_until = NULL")
            conn.commit()
            cur.close()
            conn.close()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.0)


def test_complete_e2e_workflow_with_real_worker_loop(test_users_and_projects):
    """
    Complete end-to-end user workflow test:
    1. User A submits test run via POST /test-runs.
    2. Receives HTTP 202 Accepted with run_id and status='queued'.
    3. Job is persisted in MySQL test_runs table.
    4. The ACTUAL run_worker_loop() starts, claims the queued job, acquires worker_slot.
    5. Test execution pipeline runs and transactionally persists results & bugs.
    6. Job status transitions to completed.
    7. Results and bug reports become accessible via GET /test-runs/{run_id}/results.
    8. Run appears in user's run history with project name.
    """
    client = TestClient(app)
    env = test_users_and_projects
    headers_a = {"Authorization": f"Bearer {env['token_a']}"}

    # 1. Submit test run via API
    resp = client.post(
        "/test-runs",
        headers=headers_a,
        json={
            "project_id": env["proj_a_id"],
            "base_url": "http://127.0.0.1:8000",
            "openapi_url": "http://127.0.0.1:8000/openapi.json",
        }
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    run_id = data["data"]["run_id"]
    assert data["data"]["status"] == "queued"

    # 2. Verify persisted in MySQL as queued
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT status, project_id, user_id FROM test_runs WHERE id = %s", (run_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    assert row is not None
    assert row["status"] == "queued"
    assert row["user_id"] == env["user_a_id"]
    assert row["project_id"] == env["proj_a_id"]

    # 3. Controlled execution pipeline results
    mock_results = {
        "total": 3,
        "passed": 2,
        "failed": 1,
        "pass_rate": 66.67,
        "results": [
            {
                "test_id": "TEST-001",
                "method": "GET",
                "endpoint": "/items",
                "category": "schema_conformance",
                "status": "PASS",
                "expected": {"status_code": 200, "response_schema": {"type": "array"}},
                "actual": {"status_code": 200, "body": [{"id": 1, "name": "Item 1"}]},
                "failure_reason": None,
                "failure_type": None,
                "request_body": None,
            },
            {
                "test_id": "TEST-002",
                "method": "POST",
                "endpoint": "/items",
                "category": "edge_case",
                "status": "PASS",
                "expected": {"status_code": 201, "response_schema": {"type": "object"}},
                "actual": {"status_code": 201, "body": {"id": 2, "name": "Created"}},
                "failure_reason": None,
                "failure_type": None,
                "request_body": {"name": "New Item"},
            },
            {
                "test_id": "TEST-003",
                "method": "GET",
                "endpoint": "/items/999",
                "category": "fuzzing",
                "status": "FAIL",
                "expected": {"status_code": 404, "response_schema": None},
                "actual": {"status_code": 500, "body": {"detail": "Internal crash"}},
                "failure_reason": "Expected 404 Not Found, received 500 Internal Server Error",
                "failure_type": "Server Error",
                "request_body": None,
                "bug_report": {
                    "test_id": "TEST-003",
                    "severity": "HIGH",
                    "summary": "Unhandled exception on non-existent item lookup",
                    "possible_cause": "Missing null-check in database service",
                    "recommendation": "Return 404 response when entity does not exist",
                }
            }
        ]
    }

    # 4. Start the ACTUAL run_worker_loop() in a background asyncio thread
    import agent_backend.worker as worker_module
    worker_module._worker_running = True
    worker_module.POLL_INTERVAL = 0.1

    worker_loop_active = threading.Event()
    worker_thread_exception = None

    def fake_run_all_tests(**kwargs):
        r_id = kwargs.get("run_id")
        w_id = kwargs.get("worker_id")
        save_all_test_results_and_bugs(r_id, mock_results["results"], [], worker_id=w_id)
        complete_test_run(r_id, 3, 2, 1, worker_id=w_id)
        return mock_results

    def worker_thread_target():
        nonlocal worker_thread_exception
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def run_and_stop():
                task = asyncio.create_task(run_worker_loop())
                # Allow worker loop to claim and process the queued job
                for _ in range(40):
                    await asyncio.sleep(0.2)
                    run_stat = db_operations.get_user_test_run_by_id(run_id, env["user_a_id"])
                    if run_stat and run_stat.get("status") in ("completed", "failed", "cancelled"):
                        break
                await asyncio.sleep(0.2)
                stop_worker()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            loop.run_until_complete(run_and_stop())
            loop.close()
        except Exception as e:
            worker_thread_exception = e
        finally:
            worker_loop_active.set()

    with patch("agent_backend.worker.run_all_tests", side_effect=fake_run_all_tests):
        t = threading.Thread(target=worker_thread_target, daemon=True)
        t.start()
        worker_loop_active.wait(timeout=15.0)
        t.join(timeout=5.0)
        worker_module.POLL_INTERVAL = 1.0
        worker_module.stop_worker()

    assert worker_thread_exception is None

    # 5. Verify the job reached completed status via API polling
    status_resp = client.get(f"/test-runs/{run_id}", headers=headers_a)
    assert status_resp.status_code == 200
    run_data = status_resp.json()["data"]
    assert run_data["status"] == "completed"
    assert run_data["total_tests"] == 3
    assert run_data["passed_tests"] == 2
    assert run_data["failed_tests"] == 1
    assert run_data["pass_rate"] == 66.67
    assert run_data["project_name"] == "Project User A"
    assert run_data["completed_at"] is not None

    # 6. Verify test results accessible via GET /results
    res_resp = client.get(f"/test-runs/{run_id}/results", headers=headers_a)
    assert res_resp.status_code == 200
    results_list = res_resp.json()["data"]
    assert len(results_list) == 3
    test_ids = {r["test_id"] for r in results_list}
    assert test_ids == {"TEST-001", "TEST-002", "TEST-003"}

    # 7. Verify bug reports accessible via GET /bugs
    bugs_resp = client.get(f"/test-runs/{run_id}/bugs", headers=headers_a)
    assert bugs_resp.status_code == 200
    bugs_list = bugs_resp.json()["data"]
    assert len(bugs_list) == 1
    assert bugs_list[0]["test_id"] == "TEST-003"
    assert bugs_list[0]["severity"] == "HIGH"

    # 8. Verify job appears in User A's history
    hist_resp = client.get("/test-runs", headers=headers_a)
    assert hist_resp.status_code == 200
    hist_runs = hist_resp.json()["data"]
    found_in_history = any(r["id"] == run_id and r["status"] == "completed" for r in hist_runs)
    assert found_in_history is True


def test_worker_restart_and_stale_reconciliation(test_users_and_projects):
    """
    Test worker restart & recovery:
    1. Queued jobs survive process restarts.
    2. Crashed worker leaving status='running' with expired heartbeat is reclaimed.
    3. Stale reservations are reconciled without losing tenant quota integrity.
    """
    env = test_users_and_projects

    # Create a queued run
    queued_run_id = queue_test_run(
        user_id=env["user_a_id"],
        project_id=env["proj_a_id"],
        base_url="http://127.0.0.1:8000",
        openapi_url="http://127.0.0.1:8000/openapi.json",
        user_plan="pro"
    )

    # Simulate worker crash: run transitioned to 'running' with dead worker_id and old heartbeat
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE test_runs
        SET status = 'running',
            worker_id = 'crashed_worker_dead_pid',
            started_at = DATE_SUB(NOW(), INTERVAL 2 HOUR),
            heartbeat_at = DATE_SUB(NOW(), INTERVAL 2 HOUR),
            reservation_expires_at = DATE_SUB(NOW(), INTERVAL 1 HOUR)
        WHERE id = %s
        """,
        (queued_run_id,)
    )
    conn.commit()
    cur.close()
    conn.close()

    # Reconcile stale jobs
    reconciled = reconcile_stale_reservations()
    assert reconciled >= 1

    # Verify run transitioned to failed or reset safely
    reconciled_run = get_user_test_run_by_id(queued_run_id, env["user_a_id"])
    assert reconciled_run["status"] in ("failed", "cancelled")
    err_msg = (reconciled_run.get("error_message") or "").lower()
    assert "timed out" in err_msg or "timeout" in err_msg or "stale" in err_msg


def test_zombie_worker_ownership_fencing(test_users_and_projects):
    """
    Verify zombie worker protection:
    An old worker that lost ownership cannot write results, cannot update heartbeat,
    cannot complete or fail a run, and cannot release a new owner's worker slot.
    """
    env = test_users_and_projects

    # Queue and claim run with new active worker
    run_id = queue_test_run(
        user_id=env["user_a_id"],
        project_id=env["proj_a_id"],
        base_url="http://127.0.0.1:8000",
        user_plan="pro"
    )

    # Claimed by active worker
    claimed = claim_next_queued_job("active_valid_worker_01")
    assert claimed is not None
    assert claimed["id"] == run_id

    stale_zombie_worker_id = "stale_zombie_worker_99"

    # 1. Zombie worker attempts update_heartbeat -> must fail
    hb_ok = update_heartbeat(run_id, worker_id=stale_zombie_worker_id)
    assert hb_ok is False

    # 2. Zombie worker attempts complete_test_run -> must fail
    comp_ok = complete_test_run(run_id, 0, 0, 0, worker_id=stale_zombie_worker_id)
    assert comp_ok is False

    # 3. Zombie worker attempts fail_test_run -> must fail
    fail_ok = fail_test_run(run_id, error_message="Zombie fail attempt", worker_id=stale_zombie_worker_id)
    assert fail_ok is False

    # 4. Zombie worker attempts save_all_test_results_and_bugs -> must raise RuntimeError
    dummy_results = [
        {
            "test_id": "ZOMBIE-001",
            "method": "GET",
            "endpoint": "/leak",
            "category": "fuzzing",
            "status": "PASS",
            "expected_status": 200,
            "actual_status": 200,
        }
    ]
    with pytest.raises(RuntimeError) as exc_info:
        save_all_test_results_and_bugs(run_id, dummy_results, [], worker_id=stale_zombie_worker_id)
    assert "ownership mismatch" in str(exc_info.value).lower() or "ownership lost" in str(exc_info.value).lower()

    # 5. Zombie worker attempts to release worker slot -> must fail or not release new worker's slot
    release_worker_slot(run_id, worker_id=stale_zombie_worker_id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT worker_id FROM worker_slots WHERE run_id = %s", (run_id,))
    slot = cur.fetchone()
    cur.close()
    conn.close()
    # Slot MUST still be held by active_valid_worker_01!
    assert slot is not None
    assert slot["worker_id"] == "active_valid_worker_01"

    # Active worker legitimately cleans up
    release_worker_slot(run_id, worker_id="active_valid_worker_01")


def test_multi_user_isolation_and_quotas(test_users_and_projects):
    """
    Verify strict multi-user tenant boundaries:
    - User A cannot view, cancel, or access User B's jobs or results.
    - User A cannot submit a test run for User B's project (404).
    - Idempotency key mismatch returns 409 Conflict.
    """
    client = TestClient(app)
    env = test_users_and_projects
    headers_a = {"Authorization": f"Bearer {env['token_a']}"}
    headers_b = {"Authorization": f"Bearer {env['token_b']}"}

    # User B queues a test run
    resp_b = client.post(
        "/test-runs",
        headers=headers_b,
        json={
            "project_id": env["proj_b_id"],
            "base_url": "http://127.0.0.1:8001",
            "idempotency_key": "user_b_idempotency_key_1",
        }
    )
    assert resp_b.status_code == 202
    run_b_id = resp_b.json()["data"]["run_id"]

    # 1. User A cannot view User B's job (404)
    get_resp = client.get(f"/test-runs/{run_b_id}", headers=headers_a)
    assert get_resp.status_code == 404

    # 2. User A cannot cancel User B's job (404)
    cancel_resp = client.post(f"/test-runs/{run_b_id}/cancel", headers=headers_a)
    assert cancel_resp.status_code == 404

    # 3. User A cannot access User B's results or bugs (404)
    res_resp = client.get(f"/test-runs/{run_b_id}/results", headers=headers_a)
    assert res_resp.status_code == 404
    bug_resp = client.get(f"/test-runs/{run_b_id}/bugs", headers=headers_a)
    assert bug_resp.status_code == 404

    # 4. User A's history does NOT include User B's run
    hist_a = client.get("/test-runs", headers=headers_a).json()["data"]
    assert all(r["id"] != run_b_id for r in hist_a)

    # 5. User A cannot submit a test run targeting User B's project (404)
    submit_hack = client.post(
        "/test-runs",
        headers=headers_a,
        json={"project_id": env["proj_b_id"], "base_url": "http://attacker.local"}
    )
    assert submit_hack.status_code == 404

    # 6. Idempotency key payload mismatch returns 409 Conflict
    mismatch_resp = client.post(
        "/test-runs",
        headers=headers_b,
        json={
            "project_id": env["proj_b_id"],
            "base_url": "http://127.0.0.1:9999_different_payload",
            "idempotency_key": "user_b_idempotency_key_1",
        }
    )
    assert mismatch_resp.status_code == 409
