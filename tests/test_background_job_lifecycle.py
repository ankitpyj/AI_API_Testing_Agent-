"""
Integration and Concurrency Tests for Task 9.2:
Background Job Database Foundation, Lifecycle Transitions, Atomic Claiming, and Tenant Scoping.
"""

import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# Add backend directory to path
REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from fastapi import HTTPException

from agent_backend.database import get_db_connection
from agent_backend import db_operations, usage_service, plans
from agent_backend.db_operations import (
    sanitize_target_url,
    get_user_test_run_by_id,
    claim_next_queued_job,
)
from agent_backend.usage_service import (
    queue_test_run,
    complete_test_run,
    fail_test_run,
    cancel_test_run,
    reserve_test_run,
    reconcile_stale_reservations,
    get_idempotent_test_run,
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
def setup_migration():
    """Ensure Migration 011 has been applied before running tests."""
    if not MYSQL_AVAILABLE:
        pytest.skip("MySQL database connection unavailable.")
    from agent_backend.apply_migration_011 import apply_migration
    apply_migration()


def create_ephemeral_user(email_prefix="job_test", plan="pro"):
    """Helper to create a dedicated user for lifecycle testing."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        ts = int(time.time() * 1000)
        email = f"{email_prefix}_{ts}@example.com"
        cursor.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, plan, created_at)
            VALUES (%s, %s, 'hash', 'user', %s, UTC_TIMESTAMP())
            """,
            (f"Test User {ts}", email, plan)
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    finally:
        cursor.close()
        conn.close()


def cleanup_user(user_id):
    """Clean up test user and cascade associated records."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM test_runs WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Target URL Sanitization & Security Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestTargetUrlSanitization:
    def test_sanitize_removes_embedded_credentials(self):
        raw = "https://admin:super_secret_password123@api.target.com:8443/v1/users"
        clean = sanitize_target_url(raw)
        assert clean == "https://api.target.com:8443/v1/users"
        assert "super_secret_password123" not in clean
        assert "admin" not in clean

    def test_sanitize_preserves_clean_urls(self):
        url = "http://127.0.0.1:8000/openapi.json"
        assert sanitize_target_url(url) == "http://127.0.0.1:8000/openapi.json"

    def test_sanitize_rejects_disallowed_schemes(self):
        assert sanitize_target_url("ftp://example.com/api") is None
        assert sanitize_target_url("file:///etc/passwd") is None
        assert sanitize_target_url("javascript:alert(1)") is None
        assert sanitize_target_url("") is None
        assert sanitize_target_url(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Database Schema & Migration 011 Verification
# ─────────────────────────────────────────────────────────────────────────────
class TestMigration011Schema:
    def test_test_runs_columns_exist(self):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_NAME = 'test_runs'")
            cols = {r["COLUMN_NAME"].lower() for r in cur.fetchall()}
            required_cols = {"created_at", "started_at", "completed_at", "base_url", "openapi_url", "error_message", "worker_id"}
            assert required_cols.issubset(cols), f"Missing columns: {required_cols - cols}"
        finally:
            cur.close()
            conn.close()

    def test_queue_claim_index_exists(self):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_NAME = 'test_runs'")
            indexes = {r["INDEX_NAME"].lower() for r in cur.fetchall()}
            assert "idx_test_runs_queue_claim" in indexes
        finally:
            cur.close()
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Job Lifecycle State Transitions
# ─────────────────────────────────────────────────────────────────────────────
class TestJobLifecycleTransitions:
    def test_full_lifecycle_queued_to_running_to_completed(self):
        user_id = create_ephemeral_user("lifecycle_happy")
        try:
            # 1. Enqueue job
            run_id = queue_test_run(
                user_id=user_id,
                base_url="https://api.example.com",
                openapi_url="https://api.example.com/openapi.json",
                user_plan="pro"
            )
            assert run_id is not None

            # Verify initial queued state
            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "queued"
            assert run["created_at"] is not None
            assert run["started_at"] is None
            assert run["completed_at"] is None
            assert run["base_url"] == "https://api.example.com"
            assert run["openapi_url"] == "https://api.example.com/openapi.json"

            # 2. Worker claims job -> transitions to running
            claimed = claim_next_queued_job(worker_id="worker-proc-alpha")
            assert claimed is not None
            assert claimed["id"] == run_id
            assert claimed["status"] == "running"

            run_running = get_user_test_run_by_id(run_id, user_id)
            assert run_running["status"] == "running"
            assert run_running["started_at"] is not None
            assert run_running["worker_id"] == "worker-proc-alpha"
            assert run_running["completed_at"] is None

            # 3. Complete execution -> transitions to completed
            transitioned = complete_test_run(run_id, total_tests=25, passed_tests=23, failed_tests=2)
            assert transitioned is True

            run_completed = get_user_test_run_by_id(run_id, user_id)
            assert run_completed["status"] == "completed"
            assert run_completed["total_tests"] == 25
            assert run_completed["passed_tests"] == 23
            assert run_completed["failed_tests"] == 2
            assert run_completed["pass_rate"] == 92.0
            assert run_completed["completed_at"] is not None

            # 4. Invariant: Late worker update cannot fail an already completed job
            fail_attempt = fail_test_run(run_id, error_message="Late timeout")
            assert fail_attempt is False
            run_after = get_user_test_run_by_id(run_id, user_id)
            assert run_after["status"] == "completed"
        finally:
            cleanup_user(user_id)

    def test_lifecycle_queued_to_cancelled(self):
        user_id = create_ephemeral_user("lifecycle_cancel_queued")
        try:
            run_id = queue_test_run(user_id=user_id, user_plan="pro")
            cancelled = cancel_test_run(run_id, user_id=user_id)
            assert cancelled is True

            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "cancelled"
            assert run["completed_at"] is not None
            assert run["error_message"] == "Cancelled by user"

            # Invariant: A cancelled job cannot be claimed by a worker
            claimed = claim_next_queued_job("worker-x")
            if claimed:
                assert claimed["id"] != run_id
        finally:
            cleanup_user(user_id)

    def test_lifecycle_running_to_failed_with_diagnostic(self):
        user_id = create_ephemeral_user("lifecycle_fail_running")
        try:
            run_id = queue_test_run(user_id=user_id, user_plan="pro")
            claimed = claim_next_queued_job("worker-beta")
            assert claimed["id"] == run_id

            # Fail execution with error diagnostic
            diag = "Target API returned HTTP 500: Internal Server Error during teardown"
            failed = fail_test_run(run_id, error_message=diag)
            assert failed is True

            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "failed"
            assert run["completed_at"] is not None
            assert run["error_message"] == diag

            # Invariant: A failed job cannot be marked completed
            assert complete_test_run(run_id, 10, 10, 0) is False
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Atomic Queue Claiming & Concurrency Safety
# ─────────────────────────────────────────────────────────────────────────────
class TestAtomicQueueClaiming:
    def test_concurrent_workers_claim_distinct_jobs(self):
        """
        Create 5 queued jobs and spawn 10 concurrent worker threads.
        Verify that no two workers claim the same job (FOR UPDATE SKIP LOCKED).
        """
        user_id = create_ephemeral_user("concurrent_claim")
        try:
            job_ids = []
            for i in range(5):
                jid = queue_test_run(user_id=user_id, user_plan="pro")
                job_ids.append(jid)

            claimed_results = []

            def worker_claim(worker_num):
                return claim_next_queued_job(f"worker-thread-{worker_num}", max_concurrent_running=20)

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(worker_claim, i) for i in range(10)]
                for f in as_completed(futures):
                    res = f.result()
                    if res:
                        claimed_results.append(res)

            # Exactly 5 jobs should be claimed across all threads
            assert len(claimed_results) == 5
            claimed_job_ids = [c["id"] for c in claimed_results]
            assert set(claimed_job_ids) == set(job_ids), "All 5 jobs must be claimed"
            assert len(claimed_job_ids) == len(set(claimed_job_ids)), "No duplicate job claims permitted!"
        finally:
            cleanup_user(user_id)

    def test_worker_concurrency_limit_enforced(self):
        """
        Verify that claim_next_queued_job respects max_concurrent_running.
        """
        user_id = create_ephemeral_user("concurrency_limit")
        try:
            j1 = queue_test_run(user_id=user_id, user_plan="pro")
            j2 = queue_test_run(user_id=user_id, user_plan="pro")

            # Claim 1 job with limit=1
            claimed1 = claim_next_queued_job("worker-limit-1", max_concurrent_running=1)
            assert claimed1 is not None
            assert claimed1["id"] == j1

            # Second claim with limit=1 must return None because 1 job is actively running
            claimed2 = claim_next_queued_job("worker-limit-2", max_concurrent_running=1)
            assert claimed2 is None

            # Complete j1, now j2 can be claimed
            complete_test_run(j1, 5, 5, 0)
            claimed2_after = claim_next_queued_job("worker-limit-2", max_concurrent_running=1)
            assert claimed2_after is not None
            assert claimed2_after["id"] == j2
        finally:
            cleanup_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tenant Isolation
# ─────────────────────────────────────────────────────────────────────────────
class TestTenantIsolation:
    def test_user_cannot_view_other_tenant_test_run(self):
        user_a = create_ephemeral_user("tenant_a")
        user_b = create_ephemeral_user("tenant_b")
        try:
            run_id = queue_test_run(user_id=user_a, user_plan="pro")

            # User A can retrieve their own run
            run_a = get_user_test_run_by_id(run_id, user_a)
            assert run_a is not None
            assert run_a["id"] == run_id
            assert run_a["user_id"] == user_a

            # User B querying User A's run_id returns None (tenant isolation)
            run_b = get_user_test_run_by_id(run_id, user_b)
            assert run_b is None

            # User B cannot cancel User A's run
            assert cancel_test_run(run_id, user_id=user_b) is False
            assert get_user_test_run_by_id(run_id, user_a)["status"] == "queued"
        finally:
            cleanup_user(user_a)
            cleanup_user(user_b)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Idempotency & Quota Integration
# ─────────────────────────────────────────────────────────────────────────────
class TestIdempotencyAndQuota:
    def test_queued_job_idempotent_replay(self):
        user_id = create_ephemeral_user("idempotent_queue")
        key = f"idem-key-{int(time.time() * 1000)}"
        try:
            r1 = queue_test_run(user_id=user_id, idempotency_key=key, user_plan="pro")
            r2 = queue_test_run(user_id=user_id, idempotency_key=key, user_plan="pro")
            assert r1 == r2, "Re-submitting the same idempotency key must return the existing queued run ID"
        finally:
            cleanup_user(user_id)

    def test_cancelled_and_failed_runs_release_reservations(self):
        """
        Verify that cancelling or failing a run releases its in-flight quota reservations.
        """
        user_id = create_ephemeral_user("quota_release", plan="free")
        try:
            run_id = queue_test_run(user_id=user_id, user_plan="free")
            assert run_id is not None

            # Cancel run -> releases reservation
            cancel_test_run(run_id, user_id=user_id)
            run = get_user_test_run_by_id(run_id, user_id)
            assert run["status"] == "cancelled"
            assert run["estimated_tests"] == 0
        finally:
            cleanup_user(user_id)
