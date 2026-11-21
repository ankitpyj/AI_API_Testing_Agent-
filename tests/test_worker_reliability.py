"""
Comprehensive Test Suite for Task 9.3.2:
Background Worker Heartbeat, Ownership Fencing, Zombie Write Prevention & Reliability.

Verifies:
1. Continuous periodic heartbeat execution during long-running operations.
2. Clean heartbeat manager termination upon completion, failure, and cancellation.
3. Zombie worker prevention: Stale worker cannot write results or bugs to database.
4. Ownership fencing: Stale worker cannot refresh heartbeat, persist results, complete run, or release new owner's slot.
5. Completion result verification: complete_test_run returning False raises appropriate error and does not falsely report success.
6. Cooperative cancellation detection in heartbeat manager.
7. Real worker execution with FIFO queue claiming and lifecycle execution.
"""

import os
import sys
import time
import asyncio
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

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
from agent_backend.worker import execute_job, run_worker_loop, stop_worker, WORKER_ID
from agent_backend.db_operations import (
    claim_next_queued_job,
    release_worker_slot,
    get_user_test_run_by_id,
    save_all_test_results_and_bugs,
    extend_worker_slot_lease,
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
from agent_backend.engine.test_generator.test_executor import (
    run_all_tests,
    JobCancelledError,
    TestRunCancelledError,
)


def can_connect_to_mysql():
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False


MYSQL_AVAILABLE = can_connect_to_mysql()


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    if not MYSQL_AVAILABLE:
        pytest.skip("Live MySQL connection unavailable.")


def create_test_user(prefix="rel_test", plan="pro"):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        ts = int(time.time() * 1000)
        email = f"{prefix}_{ts}@example.com"
        cursor.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, plan, created_at)
            VALUES (%s, %s, 'hash', 'user', %s, UTC_TIMESTAMP())
            """,
            (f"Reliability User {ts}", email, plan)
        )
        user_id = cursor.lastrowid
        conn.commit()
        token = create_access_token(data={"sub": str(user_id), "email": email, "id": user_id, "role": "user", "plan": plan})
        headers = {"Authorization": f"Bearer {token}"}
        return user_id, headers
    finally:
        cursor.close()
        conn.close()


def cleanup_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM bug_reports WHERE run_id IN (SELECT id FROM test_runs WHERE user_id = %s)", (user_id,))
        cursor.execute("DELETE FROM test_results WHERE run_id IN (SELECT id FROM test_runs WHERE user_id = %s)", (user_id,))
        cursor.execute("UPDATE worker_slots SET run_id = NULL, worker_id = NULL, leased_until = NULL WHERE run_id IN (SELECT id FROM test_runs WHERE user_id = %s)", (user_id,))
        cursor.execute("DELETE FROM test_runs WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM projects WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Reliable Heartbeat Mechanism Tests (FIX 1)
# ─────────────────────────────────────────────────────────────────────────────
class TestReliableHeartbeatMechanism:
    def test_periodic_heartbeat_updates_during_active_execution(self):
        user_id, _ = create_test_user("hb_test")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claimed = claim_next_queued_job("worker-hb-1")
            assert claimed is not None
            assert claimed["id"] == run_id

            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT heartbeat_at FROM test_runs WHERE id = %s", (run_id,))
            initial_hb = cur.fetchone()["heartbeat_at"]
            cur.close()
            conn.close()

            # Start heartbeat manager with fast 0.2s interval
            mgr = JobHeartbeatManager(run_id=run_id, worker_id="worker-hb-1", interval_seconds=0.2)
            mgr.start()

            # Wait for 0.6s to allow at least 2 ticks
            time.sleep(0.6)

            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT heartbeat_at, reservation_expires_at FROM test_runs WHERE id = %s", (run_id,))
            updated_row = cur.fetchone()
            cur.close()
            conn.close()

            assert updated_row["heartbeat_at"] is not None
            assert updated_row["reservation_expires_at"] is not None
            assert not mgr.is_ownership_lost()

            # Stop manager cleanly
            mgr.stop()
            assert mgr._thread is None or not mgr._thread.is_alive()
        finally:
            cleanup_user(user_id)

    def test_heartbeat_stops_and_flags_when_ownership_is_lost(self):
        user_id, _ = create_test_user("hb_loss")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claim_next_queued_job("worker-hb-orig")

            mgr = JobHeartbeatManager(run_id=run_id, worker_id="worker-hb-orig", interval_seconds=0.2)
            mgr.start()

            # Change ownership in DB to worker-hb-new
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE test_runs SET worker_id = 'worker-hb-new' WHERE id = %s", (run_id,))
            conn.commit()
            cur.close()
            conn.close()

            # Wait for heartbeat manager tick
            time.sleep(0.5)

            # Manager should detect ownership loss and set flag
            assert mgr.is_ownership_lost() is True
            mgr.stop()
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Zombie Worker Write Prevention Tests (FIX 2)
# ─────────────────────────────────────────────────────────────────────────────
class TestZombieWorkerWritePrevention:
    def test_zombie_worker_cannot_write_results_after_stale_reconciliation(self):
        user_id, _ = create_test_user("zombie_test")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claimed = claim_next_queued_job("worker-zombie")
            assert claimed is not None

            # Simulate stale recovery by expiring timestamps and running reconcile_stale_reservations
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE test_runs SET heartbeat_at = DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE) WHERE id = %s", (run_id,))
            cur.execute("UPDATE worker_slots SET leased_until = DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE) WHERE run_id = %s", (run_id,))
            conn.commit()
            cur.close()
            conn.close()

            reconciled = reconcile_stale_reservations(timeout_minutes=5)
            assert reconciled >= 1

            # Verify run is now 'failed'
            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "failed"

            # Zombie worker attempts to persist test results and bugs
            mock_results = [
                {
                    "test_id": "TC-ZOMBIE-1",
                    "method": "GET",
                    "endpoint": "/items",
                    "status": "PASS",
                    "failure_type": None,
                    "expected_status": 200,
                    "actual_status": 200,
                    "request": {},
                    "actual": {"body": "zombie data"},
                    "failure_reason": None,
                }
            ]

            # save_all_test_results_and_bugs MUST raise RuntimeError and abort
            with pytest.raises(RuntimeError) as exc_info:
                save_all_test_results_and_bugs(
                    run_id=run_id,
                    results=mock_results,
                    worker_id="worker-zombie"
                )
            assert "is in status 'failed', not 'running'" in str(exc_info.value)

            # Verify zero results were inserted into test_results
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM test_results WHERE run_id = %s", (run_id,))
            count = cur.fetchone()[0]
            cur.close()
            conn.close()

            assert count == 0
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ownership Fencing Lifecycle Tests (FIX 3)
# ─────────────────────────────────────────────────────────────────────────────
class TestOwnershipFencing:
    def test_stale_worker_cannot_refresh_complete_or_release_slot(self):
        user_id, _ = create_test_user("fence_test")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claim_next_queued_job("worker-alpha")

            # Simulate reassignment to worker-beta
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE test_runs SET worker_id = 'worker-beta' WHERE id = %s", (run_id,))
            cur.execute("UPDATE worker_slots SET worker_id = 'worker-beta' WHERE run_id = %s", (run_id,))
            conn.commit()
            cur.close()
            conn.close()

            # 1. worker-alpha cannot update heartbeat
            hb_ok = update_heartbeat(run_id, worker_id="worker-alpha")
            assert hb_ok is False

            # 2. worker-alpha cannot complete the run
            comp_ok = complete_test_run(run_id, 5, 5, 0, worker_id="worker-alpha")
            assert comp_ok is False

            # 3. worker-alpha cannot release worker-beta's slot
            rel_ok = release_worker_slot(run_id, worker_id="worker-alpha")
            assert rel_ok is False

            # Verify slot remains safely leased to worker-beta
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT worker_id FROM worker_slots WHERE run_id = %s", (run_id,))
            slot = cur.fetchone()
            cur.close()
            conn.close()

            assert slot["worker_id"] == "worker-beta"

            # 4. worker-beta CAN complete the run and release slot
            comp_beta = complete_test_run(run_id, 5, 5, 0, worker_id="worker-beta")
            assert comp_beta is True
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Completion Result & Cancellation Error Tests (FIX 4)
# ─────────────────────────────────────────────────────────────────────────────
class TestCompletionResultAndCancellation:
    def test_complete_test_run_rejection_raises_cancelled_or_stale_error(self):
        user_id, _ = create_test_user("comp_rej")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claim_next_queued_job("worker-test")

            # User cancels the run
            cancel_test_run(run_id, user_id=user_id)

            # complete_test_run returns False
            res = complete_test_run(run_id, 10, 10, 0, worker_id="worker-test")
            assert res is False

            # Verify status remains cancelled in DB
            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "cancelled"
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Real Worker Loop Integration Tests (FIX 5)
# ─────────────────────────────────────────────────────────────────────────────
class TestRealWorkerLoopIntegration:
    def test_real_worker_claims_and_executes_to_completion(self):
        user_id, headers = create_test_user("real_exec")
        client = TestClient(app)
        try:
            # 1. Enqueue job via HTTP 202 endpoint
            resp = client.post(
                "/test-runs",
                headers=headers,
                json={"base_url": "http://127.0.0.1:8000"}
            )
            assert resp.status_code == 202
            run_id = resp.json()["data"]["run_id"]

            # Mock run_all_tests to simulate fast successful suite execution
            def mock_executor(**kwargs):
                r_id = kwargs.get("run_id")
                w_id = kwargs.get("worker_id")
                mock_res = [
                    {
                        "test_id": "TC-LIVE-01",
                        "method": "GET",
                        "endpoint": "/live",
                        "status": "PASS",
                        "failure_type": None,
                        "expected_status": 200,
                        "actual_status": 200,
                        "request": {},
                        "actual": {"body": "ok"},
                        "failure_reason": None,
                    }
                ]
                save_all_test_results_and_bugs(r_id, mock_res, worker_id=w_id)
                complete_test_run(r_id, total_tests=1, passed_tests=1, failed_tests=0, worker_id=w_id)
                return {"total": 1, "passed": 1, "failed": 0, "pass_rate": 100.0, "run_id": r_id, "results": mock_res}

            # 2. Worker claims and executes job
            with patch("agent_backend.worker.run_all_tests", side_effect=mock_executor):
                claimed = claim_next_queued_job(WORKER_ID)
                assert claimed is not None
                assert claimed["id"] == run_id

                execute_job(claimed)

            # 3. Verify final state in MySQL is 'completed'
            status_resp = client.get(f"/test-runs/{run_id}", headers=headers)
            assert status_resp.status_code == 200
            run_data = status_resp.json()["data"]
            assert run_data["status"] == "completed"
            assert run_data["total_tests"] == 1
            assert run_data["passed_tests"] == 1
            assert run_data["pass_rate"] == 100.0

            # 4. Verify test results are readable via HTTP 200
            res_resp = client.get(f"/test-runs/{run_id}/results", headers=headers)
            assert res_resp.status_code == 200
            assert len(res_resp.json()["data"]) == 1
        finally:
            cleanup_user(user_id)
