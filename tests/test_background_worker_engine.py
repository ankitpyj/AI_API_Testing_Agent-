"""
Comprehensive Test Suite for Task 9.3:
Background Worker Engine, MySQL Job Queue, and Job Management APIs.

Covers:
1. HTTP 202 Accepted job submission (POST /test-runs).
2. Status polling and lifecycle transitions (GET /test-runs/{run_id}).
3. Strict multi-tenant isolation on all job endpoints.
4. Immediate queued cancellation and cooperative running cancellation (POST /test-runs/{run_id}/cancel).
5. HTTP 409 Conflict protection on in-flight results and bug reports access.
6. Idempotency payload hash validation (replaying same payload vs 409 on mismatched payload).
7. Atomic worker_slots concurrency enforcement under competing threads.
8. Transactional persistence atomicity and diagnostic sanitization.
"""

import sys
import time
import json
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi.testclient import TestClient

from agent_backend.database import get_db_connection
from agent_backend import db_operations, usage_service, plans
from agent_backend.app import app
from agent_backend.auth import create_access_token
from agent_backend.worker import execute_job, WORKER_ID
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
)
from agent_backend.engine.authentication.response_sanitizer import (
    sanitize_error_message,
    sanitize_string,
    sanitize_data,
)
from agent_backend.engine.test_generator.test_executor import (
    JobCancelledError,
    is_test_run_cancelled,
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
def setup_migrations():
    """Ensure Migrations 011 and 012 have been applied."""
    if not MYSQL_AVAILABLE:
        pytest.skip("Live MySQL connection unavailable.")
    from agent_backend.apply_migration_011 import apply_migration as m11
    from agent_backend.apply_migration_012 import apply_migration as m12
    m11()
    m12()


def create_test_user(prefix="worker_test", plan="pro"):
    """Helper to create an isolated user and JWT bearer header."""
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
            (f"Worker User {ts}", email, plan)
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
    """Clean up user and cascade test runs."""
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
# 1. Asynchronous Job Submission (HTTP 202 Accepted) & Polling
# ─────────────────────────────────────────────────────────────────────────────
class TestJobSubmissionAndPolling:
    def test_post_test_runs_returns_202_accepted(self):
        user_id, headers = create_test_user("sub_202")
        client = TestClient(app)
        try:
            resp = client.post(
                "/test-runs",
                headers=headers,
                json={
                    "base_url": "http://127.0.0.1:8000",
                    "openapi_url": "http://127.0.0.1:8000/openapi.json"
                }
            )
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "accepted"
            assert "data" in body
            run_id = body["data"]["run_id"]
            assert body["data"]["status"] == "queued"

            # Verify in DB
            status_resp = client.get(f"/test-runs/{run_id}", headers=headers)
            assert status_resp.status_code == 200
            run_data = status_resp.json()["data"]
            assert run_data["id"] == run_id
            assert run_data["status"] == "queued"
            assert run_data["user_id"] == user_id
            assert run_data["total_tests"] == 0
            assert run_data["pass_rate"] == 0.0
        finally:
            cleanup_user(user_id)

    def test_results_and_bugs_return_409_while_queued_or_running(self):
        user_id, headers = create_test_user("conflict_test")
        client = TestClient(app)
        try:
            # Create a queued run
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")

            # Try to fetch results and bugs while queued
            res_queued = client.get(f"/test-runs/{run_id}/results", headers=headers)
            assert res_queued.status_code == 409
            assert "not available" in res_queued.json()["detail"].lower()

            bugs_queued = client.get(f"/test-runs/{run_id}/bugs", headers=headers)
            assert bugs_queued.status_code == 409

            # Transition to running
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE test_runs SET status = 'running' WHERE id = %s", (run_id,))
            conn.commit()
            cur.close()
            conn.close()

            # Try to fetch while running
            res_running = client.get(f"/test-runs/{run_id}/results", headers=headers)
            assert res_running.status_code == 409

            # Transition to completed
            complete_test_run(run_id, total_tests=5, passed_tests=5, failed_tests=0)

            # Now results and bugs should succeed (HTTP 200)
            res_completed = client.get(f"/test-runs/{run_id}/results", headers=headers)
            assert res_completed.status_code == 200
            assert isinstance(res_completed.json()["data"], list)
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Multi-Tenant Isolation
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiTenantIsolation:
    def test_tenant_cannot_poll_or_cancel_other_tenant_run(self):
        user_a, headers_a = create_test_user("tenant_a")
        user_b, headers_b = create_test_user("tenant_b")
        client = TestClient(app)
        try:
            # User A queues a run
            run_id_a = queue_test_run(user_a, base_url="http://127.0.0.1:8000")

            # User B attempts to view status
            resp_status = client.get(f"/test-runs/{run_id_a}", headers=headers_b)
            assert resp_status.status_code == 404

            # User B attempts to cancel
            resp_cancel = client.post(f"/test-runs/{run_id_a}/cancel", headers=headers_b)
            assert resp_cancel.status_code == 404

            # User B attempts to view results
            resp_results = client.get(f"/test-runs/{run_id_a}/results", headers=headers_b)
            assert resp_results.status_code == 404

            # Verify run A remains queued and uncancelled
            run_a = get_user_test_run_by_id(run_id_a, user_a)
            assert run_a["status"] == "queued"
        finally:
            cleanup_user(user_a)
            cleanup_user(user_b)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cancellation (Immediate Queued vs Cooperative Running)
# ─────────────────────────────────────────────────────────────────────────────
class TestCancellationLifecycle:
    def test_queued_cancellation_releases_slot_and_updates_status(self):
        user_id, headers = create_test_user("cancel_queued")
        client = TestClient(app)
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            resp = client.post(f"/test-runs/{run_id}/cancel", headers=headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
            body = resp.json()
            assert body["status"] == "success"
            assert body["data"]["status"] == "cancelled"

            # Check DB status
            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "cancelled"
            assert run["completed_at"] is not None
            assert "Cancelled" in run["error_message"]

            # Cancelling already finished run returns 400
            second_cancel = client.post(f"/test-runs/{run_id}/cancel", headers=headers)
            assert second_cancel.status_code == 400
        finally:
            cleanup_user(user_id)

    def test_cooperative_cancellation_detection(self):
        user_id, _ = create_test_user("coop_cancel")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            assert is_test_run_cancelled(run_id) is False

            # Mark cancelled
            cancel_test_run(run_id, user_id=user_id)
            assert is_test_run_cancelled(run_id) is True
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency & Payload Hash Replay Protection
# ─────────────────────────────────────────────────────────────────────────────
class TestIdempotencyPayloadHash:
    def test_idempotent_replay_with_same_payload(self):
        user_id, headers = create_test_user("idem_same")
        client = TestClient(app)
        try:
            key = f"idem-key-{int(time.time() * 1000)}"
            payload = {
                "base_url": "http://127.0.0.1:8000",
                "openapi_url": "http://127.0.0.1:8000/openapi.json",
                "idempotency_key": key
            }

            resp1 = client.post("/test-runs", headers=headers, json=payload)
            assert resp1.status_code == 202
            run_id_1 = resp1.json()["data"]["run_id"]

            # Submit exact same request again
            resp2 = client.post("/test-runs", headers=headers, json=payload)
            assert resp2.status_code == 202
            run_id_2 = resp2.json()["data"]["run_id"]

            assert run_id_1 == run_id_2
        finally:
            cleanup_user(user_id)

    def test_mismatched_payload_raises_409_conflict(self):
        user_id, headers = create_test_user("idem_diff")
        client = TestClient(app)
        try:
            key = f"idem-diff-{int(time.time() * 1000)}"
            payload1 = {
                "base_url": "http://127.0.0.1:8000",
                "openapi_url": "http://127.0.0.1:8000/openapi.json",
                "idempotency_key": key
            }
            resp1 = client.post("/test-runs", headers=headers, json=payload1)
            assert resp1.status_code == 202

            # Submit same key with DIFFERENT base_url
            payload2 = {
                "base_url": "http://127.0.0.1:9000",
                "openapi_url": "http://127.0.0.1:8000/openapi.json",
                "idempotency_key": key
            }
            resp2 = client.post("/test-runs", headers=headers, json=payload2)
            assert resp2.status_code == 409
            assert "different request payload" in resp2.json()["detail"].lower()
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Atomic worker_slots Concurrency Enforcement
# ─────────────────────────────────────────────────────────────────────────────
class TestAtomicWorkerSlotsConcurrency:
    def test_worker_slots_enforces_strict_concurrency_under_competing_threads(self):
        user_id, _ = create_test_user("slots_test", plan="enterprise")
        try:
            # Clean all worker slots
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE worker_slots SET run_id = NULL, worker_id = NULL, leased_until = NULL")
            conn.commit()
            cur.close()
            conn.close()

            # Enqueue 6 jobs
            job_ids = [queue_test_run(user_id, base_url=f"http://127.0.0.1:800{i}") for i in range(6)]

            # Competing threads try to claim jobs with max_concurrent_running = 2
            max_concurrency = 2
            claimed_jobs = []

            def worker_claim_attempt(w_idx):
                w_id = f"test-worker-{w_idx}"
                return claim_next_queued_job(w_id, max_concurrent_running=max_concurrency)

            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(worker_claim_attempt, i) for i in range(6)]
                for f in as_completed(futures):
                    res = f.result()
                    if res:
                        claimed_jobs.append(res)

            # Exactly max_concurrency (2) jobs should have been claimed, 4 rejected
            assert len(claimed_jobs) == max_concurrency, f"Expected {max_concurrency} claims, got {len(claimed_jobs)}"
            claimed_run_ids = [j["id"] for j in claimed_jobs]
            claimed_slots = [j["slot_id"] for j in claimed_jobs]

            # Verify unique slots and unique jobs
            assert len(set(claimed_run_ids)) == max_concurrency
            assert len(set(claimed_slots)) == max_concurrency
            assert all(s <= max_concurrency for s in claimed_slots)

            # Release one job slot
            release_worker_slot(claimed_run_ids[0])

            # Now an additional job can be claimed
            next_job = claim_next_queued_job("test-worker-extra", max_concurrent_running=max_concurrency)
            assert next_job is not None
            assert next_job["id"] not in claimed_run_ids

            # Clean up all claimed slots
            for j in claimed_jobs:
                release_worker_slot(j["id"])
            release_worker_slot(next_job["id"])
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Transactional Result Persistence & Sanitization
# ─────────────────────────────────────────────────────────────────────────────
class TestTransactionalPersistenceAndSanitization:
    def test_save_all_test_results_and_bugs_atomicity(self):
        user_id, _ = create_test_user("atomic_persist")
        try:
            run_id = queue_test_run(user_id, base_url="http://127.0.0.1:8000")
            claimed = claim_next_queued_job("test-worker-persist")
            assert claimed is not None
            assert claimed["id"] == run_id

            results = [
                {
                    "test_id": "TC-01",
                    "method": "GET",
                    "endpoint": "/users",
                    "status": "PASS",
                    "failure_type": None,
                    "expected_status": 200,
                    "expected": {"status_code": 200},
                    "actual_status": 200,
                    "actual": {"status_code": 200, "body": [{"id": 1, "name": "Alice"}]},
                    "request": {},
                    "failure_reason": None,
                },
                {
                    "test_id": "TC-02",
                    "method": "POST",
                    "endpoint": "/users",
                    "status": "FAIL",
                    "failure_type": "API_DEFECT",
                    "expected_status": 201,
                    "expected": {"status_code": 201},
                    "actual_status": 500,
                    "actual": {"status_code": 500, "body": {"error": "Internal Error", "secret": "SUPER_SECRET_KEY"}},
                    "request": {"username": "bob", "apiKey": "SUPER_SECRET_KEY"},
                    "failure_reason": "Server returned 500 with secret SUPER_SECRET_KEY",
                    "bug_report": {
                        "bug_id": "BUG-01",
                        "endpoint": "POST /users",
                        "severity": "High",
                        "summary": "Internal crash with SUPER_SECRET_KEY",
                        "possible_cause": "Unhandled exception with SUPER_SECRET_KEY",
                        "recommendation": "Fix handler with SUPER_SECRET_KEY",
                        "status": "Open"
                    }
                }
            ]

            secrets = ["SUPER_SECRET_KEY"]
            save_all_test_results_and_bugs(run_id, results, secrets=secrets, worker_id="test-worker-persist")

            # Verify persisted data in MySQL has secret REDACTED
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM test_results WHERE run_id = %s ORDER BY id", (run_id,))
            saved_results = cur.fetchall()
            assert len(saved_results) == 2
            assert "SUPER_SECRET_KEY" not in str(saved_results[1]["actual_body"])
            assert "SUPER_SECRET_KEY" not in str(saved_results[1]["request_body"])
            assert "SUPER_SECRET_KEY" not in str(saved_results[1]["failure_reason"])
            assert "[REDACTED]" in str(saved_results[1]["failure_reason"])

            cur.execute("SELECT * FROM bug_reports WHERE run_id = %s", (run_id,))
            saved_bugs = cur.fetchall()
            assert len(saved_bugs) == 1
            assert "SUPER_SECRET_KEY" not in saved_bugs[0]["summary"]
            assert "[REDACTED]" in saved_bugs[0]["summary"]

            cur.close()
            conn.close()
        finally:
            cleanup_user(user_id)

    def test_sanitize_error_message(self):
        err = Exception("Failed DB connection to mysql://admin:P@ssword123@db.internal:3306/prod with Bearer eyJhbGciOiJIUzI1Ni.tok.sig")
        clean = sanitize_error_message(err)
        assert "P@ssword123" not in clean
        assert "eyJhbGci" not in clean
        assert "Bearer [REDACTED]" in clean
        assert len(clean) <= 500
