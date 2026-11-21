"""
Genuine MySQL Concurrency Integration Tests (Task 7.4 Fix 5).

Runs real concurrent threads using independent MySQL connections against a separate,
disposable test database ('test_concurrency_db').
Never runs against or alters the production database ('defaultdb').

Tests:
1. Two or more simultaneous requests competing for the final test-run quota slot.
2. Two or more simultaneous project creations competing for the final project slot.
3. Multiple concurrent AI requests competing for the final AI operation slot.
4. Concurrent test-case reservations.
5. Duplicate idempotency keys submitted simultaneously.
6. Stale reservation cleanup racing with active heartbeat updates.
7. Database row-level lock concurrency and clean rollback behavior.
"""

import sys
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
for p in [str(REPO_ROOT), str(BACKEND_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
import mysql.connector
from fastapi import HTTPException

TEST_DB_NAME = "test_concurrency_db"

def can_connect_to_mysql():
    """Verify whether live MySQL server is reachable from the current execution environment."""
    try:
        from agent_backend.database import get_db_connection
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False

MYSQL_AVAILABLE = can_connect_to_mysql()

def get_isolated_test_connection():
    """Return a new independent connection pointing to test_concurrency_db."""
    from agent_backend.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"USE {TEST_DB_NAME}")
    cursor.close()
    return conn


@pytest.fixture(scope="module")
def setup_test_db():
    """
    Create disposable test database and tables for the concurrency test suite.
    Tears down and drops test_concurrency_db upon test module completion.
    """
    if not MYSQL_AVAILABLE:
        pytest.skip("Live MySQL connection unavailable in this sandbox environment.")

    from agent_backend.database import get_db_connection
    root_conn = get_db_connection()
    root_cursor = root_conn.cursor()

    try:
        root_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {TEST_DB_NAME}")
        root_conn.commit()

        test_conn = get_isolated_test_connection()
        test_cur = test_conn.cursor()

        # DDL for isolated test schema
        test_cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user',
                plan VARCHAR(50) NOT NULL DEFAULT 'internal_demo',
                created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """)

        test_cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                project_name VARCHAR(100) NOT NULL,
                description TEXT NULL,
                base_url VARCHAR(255) NOT NULL,
                openapi_url VARCHAR(255) NULL,
                auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
                auth_header_name VARCHAR(100) NULL DEFAULT NULL,
                auth_secret_encrypted TEXT NULL DEFAULT NULL,
                created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (user_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
        """)

        test_cur.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL DEFAULT NULL,
                project_id INT NULL DEFAULT NULL,
                created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP NULL DEFAULT NULL,
                completed_at TIMESTAMP NULL DEFAULT NULL,
                base_url VARCHAR(255) NULL DEFAULT NULL,
                openapi_url VARCHAR(255) NULL DEFAULT NULL,
                total_tests INT DEFAULT 0,
                passed_tests INT DEFAULT 0,
                failed_tests INT DEFAULT 0,
                error_message TEXT NULL DEFAULT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'completed',
                estimated_tests INT NOT NULL DEFAULT 0,
                heartbeat_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                reservation_expires_at TIMESTAMP NULL DEFAULT NULL,
                idempotency_key VARCHAR(128) NULL DEFAULT NULL,
                worker_id VARCHAR(64) NULL DEFAULT NULL,
                INDEX (user_id),
                INDEX (project_id),
                INDEX (status),
                INDEX idx_test_runs_user_idempotency (user_id, idempotency_key),
                INDEX idx_test_runs_heartbeat (status, heartbeat_at),
                INDEX idx_test_runs_queue_claim (status, created_at, id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            ) ENGINE=InnoDB;
        """)

        test_cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage_logs (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                run_id INT NULL,
                call_type VARCHAR(30) NOT NULL,
                provider VARCHAR(50) NOT NULL DEFAULT 'gemini',
                model VARCHAR(100) NOT NULL,
                input_tokens INT DEFAULT 0,
                output_tokens INT DEFAULT 0,
                total_tokens INT DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'success',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX (user_id),
                INDEX (run_id),
                INDEX (created_at)
            ) ENGINE=InnoDB;
        """)

        test_conn.commit()
        test_cur.close()
        test_conn.close()

        yield

    finally:
        try:
            root_cursor.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
            root_conn.commit()
        except Exception:
            pass
        root_cursor.close()
        root_conn.close()


@pytest.fixture
def patch_db_for_test(setup_test_db, monkeypatch):
    """Ensure all usage service and db operation calls use the isolated test database."""
    monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
    monkeypatch.setattr("agent_backend.usage_service.get_db_connection", get_isolated_test_connection)
    monkeypatch.setattr("agent_backend.db_operations.get_db_connection", get_isolated_test_connection)


def create_test_user(email: str, plan: str = "concurrency_test_plan") -> int:
    """Helper to insert an isolated user into test_concurrency_db."""
    conn = get_isolated_test_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (full_name, email, password_hash, plan) VALUES (%s, %s, 'hash', %s)",
        (f"User {email}", email, plan)
    )
    user_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return user_id


# ============================================================================
# Concurrency Scenario 1: Competing for the Final Test-Run Slot
# ============================================================================

def test_concurrent_test_run_reservations_cannot_exceed_quota(patch_db_for_test, monkeypatch):
    """
    Test 5 concurrent threads competing for the 1 remaining test run slot.
    Under real InnoDB SELECT ... FOR UPDATE row-level locking:
    Exactly 1 thread must succeed; the other 4 must receive HTTP 429.
    """
    import agent_backend.usage_service as us
    user_id = create_test_user("testrun_concurrency@example.com", plan="free")

    # Set plan limit: free allows 50 runs. Pre-seed 49 runs so exactly 1 slot remains.
    conn = get_isolated_test_connection()
    cur = conn.cursor()
    for _ in range(49):
        cur.execute(
            "INSERT INTO test_runs (user_id, status, started_at) VALUES (%s, 'completed', UTC_TIMESTAMP())",
            (user_id,)
        )
    conn.commit()
    cur.close()
    conn.close()

    successes = []
    rejections = []

    def attempt_reservation():
        try:
            run_id = us.reserve_test_run(user_id=user_id, user_plan="free")
            if run_id:
                successes.append(run_id)
        except HTTPException as exc:
            if exc.status_code == 429:
                rejections.append(exc.detail)
            else:
                raise exc

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_reservation) for _ in range(5)]
        for f in futures:
            f.result()

    assert len(successes) == 1, f"Expected exactly 1 successful reservation, got {len(successes)}"
    assert len(rejections) == 4, f"Expected 4 rejections with HTTP 429, got {len(rejections)}"

    # Confirm database state
    conn = get_isolated_test_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM test_runs WHERE user_id = %s AND status IN ('running', 'completed')", (user_id,))
    total_runs = cur.fetchone()["total"]
    cur.close()
    conn.close()
    assert total_runs == 50, f"Expected 50 total runs in database, got {total_runs}"


# ============================================================================
# Concurrency Scenario 2: Competing for the Final Project Slot
# ============================================================================

def test_concurrent_project_creation_cannot_exceed_quota(patch_db_for_test, monkeypatch):
    """
    Free plan allows max 3 projects. Pre-seed 2 projects (1 remaining).
    5 threads attempt to create a project concurrently.
    Exactly 1 must succeed; 4 must receive HTTP 429.
    """
    import agent_backend.db_operations as db_ops
    user_id = create_test_user("project_concurrency@example.com", plan="free")

    # Pre-seed 2 projects
    conn = get_isolated_test_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (user_id, project_name, base_url) VALUES (%s, 'P1', 'http://p1.com')", (user_id,))
    cur.execute("INSERT INTO projects (user_id, project_name, base_url) VALUES (%s, 'P2', 'http://p2.com')", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

    successes = []
    rejections = []

    def attempt_project_creation(idx):
        try:
            pid = db_ops.create_project(
                user_id=user_id,
                project_name=f"Project {idx}",
                base_url="http://example.com"
            )
            successes.append(pid)
        except HTTPException as exc:
            if exc.status_code == 429:
                rejections.append(exc.detail)
            else:
                raise exc

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_project_creation, i) for i in range(5)]
        for f in futures:
            f.result()

    assert len(successes) == 1, f"Expected exactly 1 project created, got {len(successes)}"
    assert len(rejections) == 4, f"Expected 4 HTTP 429 rejections, got {len(rejections)}"

    conn = get_isolated_test_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM projects WHERE user_id = %s", (user_id,))
    total_projects = cur.fetchone()["total"]
    cur.close()
    conn.close()
    assert total_projects == 3


# ============================================================================
# Concurrency Scenario 3: Multiple Concurrent AI Requests for Final AI Slot
# ============================================================================

def test_concurrent_ai_reservations_cannot_exceed_quota(patch_db_for_test, monkeypatch):
    """
    Pro plan allows 500 AI operations. Pre-seed 499 operations (1 remaining).
    5 threads call reserve_ai_operation() concurrently.
    Exactly 1 must receive a reservation ID; 4 must receive None.
    """
    import agent_backend.usage_service as us
    user_id = create_test_user("ai_concurrency@example.com", plan="pro")

    # Pre-seed 499 successful AI logs
    conn = get_isolated_test_connection()
    cur = conn.cursor()
    for _ in range(499):
        cur.execute(
            "INSERT INTO ai_usage_logs (user_id, call_type, provider, model, status, created_at) "
            "VALUES (%s, 'analysis', 'gemini', 'gemini-model', 'success', UTC_TIMESTAMP())",
            (user_id,)
        )
    conn.commit()
    cur.close()
    conn.close()

    success_ids = []
    rejections = []

    def attempt_ai_reservation():
        res_id = us.reserve_ai_operation(user_id=user_id, call_type="analysis", user_plan="pro")
        if res_id is not None:
            success_ids.append(res_id)
        else:
            rejections.append(True)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_ai_reservation) for _ in range(5)]
        for f in futures:
            f.result()

    assert len(success_ids) == 1, f"Expected exactly 1 AI reservation, got {len(success_ids)}"
    assert len(rejections) == 4, f"Expected 4 rejections (None), got {len(rejections)}"


# ============================================================================
# Concurrency Scenario 4: Concurrent Test-Case Reservations
# ============================================================================

def test_concurrent_test_case_reservations(patch_db_for_test, monkeypatch):
    """
    Free tier allows 500 monthly test cases. Pre-seed 400 completed test cases (100 remaining).
    3 concurrent runs attempt to reserve 60 test cases each.
    Run 1 succeeds (400 + 60 = 460 <= 500).
    Runs 2 and 3 require 60 each, but only 40 remain available. Both must be rejected with 429.
    """
    import agent_backend.usage_service as us
    user_id = create_test_user("testcase_concurrency@example.com", plan="free")

    # Seed run with 400 completed test cases
    conn = get_isolated_test_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO test_runs (user_id, status, total_tests, started_at) VALUES (%s, 'completed', 400, UTC_TIMESTAMP())",
        (user_id,)
    )
    # Seed 3 in-flight test runs
    cur.execute("INSERT INTO test_runs (user_id, status, started_at) VALUES (%s, 'running', UTC_TIMESTAMP())", (user_id,))
    run1 = cur.lastrowid
    cur.execute("INSERT INTO test_runs (user_id, status, started_at) VALUES (%s, 'running', UTC_TIMESTAMP())", (user_id,))
    run2 = cur.lastrowid
    cur.execute("INSERT INTO test_runs (user_id, status, started_at) VALUES (%s, 'running', UTC_TIMESTAMP())", (user_id,))
    run3 = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()

    successes = []
    rejections = []

    def attempt_tc_reservation(run_id):
        try:
            budget = us.reserve_test_case_quota(user_id=user_id, run_id=run_id, estimated_tests=60, user_plan="free")
            successes.append((run_id, budget))
        except HTTPException as exc:
            if exc.status_code == 429:
                rejections.append(exc.detail)
            else:
                raise exc

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(attempt_tc_reservation, rid) for rid in [run1, run2, run3]]
        for f in futures:
            f.result()

    assert len(successes) == 1, f"Expected 1 reservation to succeed, got {len(successes)}"
    assert len(rejections) == 2, f"Expected 2 rejections, got {len(rejections)}"


# ============================================================================
# Concurrency Scenario 5: Duplicate Idempotency Keys Submitted Simultaneously
# ============================================================================

def test_concurrent_duplicate_idempotency_keys(patch_db_for_test):
    """
    Three concurrent threads submit the exact same idempotency_key for the same user.
    Exactly 1 new test_runs row must be created; all three threads receive that same run ID.
    """
    import agent_backend.usage_service as us
    user_id = create_test_user("idemp_concurrency@example.com", plan="free")
    key = "race-key-xyz-777"

    run_ids = []

    def attempt_idempotent_run():
        rid = us.reserve_test_run(user_id=user_id, user_plan="free", idempotency_key=key)
        run_ids.append(rid)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(attempt_idempotent_run) for _ in range(3)]
        for f in futures:
            f.result()

    # All three must receive the same run_id
    assert len(run_ids) == 3
    assert run_ids[0] is not None
    assert run_ids[0] == run_ids[1] == run_ids[2]

    # Verify database has exactly 1 row for this key
    conn = get_isolated_test_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM test_runs WHERE user_id = %s AND idempotency_key = %s", (user_id, key))
    count = cur.fetchone()["total"]
    cur.close()
    conn.close()
    assert count == 1


# ============================================================================
# Concurrency Scenario 6: Stale Reservation Cleanup Racing with Heartbeat
# ============================================================================

def test_stale_cleanup_races_with_active_heartbeat(patch_db_for_test):
    """
    Run A is active and actively updating its heartbeat.
    Run B is genuinely stale (no heartbeat update for 10 minutes).
    Concurrent execution of reconcile_stale_reservations() and update_heartbeat(run_a):
    - Run A must remain 'running'.
    - Run B must be transitioned to 'failed'.
    """
    import agent_backend.usage_service as us
    user_id = create_test_user("heartbeat_concurrency@example.com")

    conn = get_isolated_test_connection()
    cur = conn.cursor()
    # Run A: started 20 mins ago, but heartbeat is fresh (0 seconds ago)
    cur.execute(
        """
        INSERT INTO test_runs (user_id, status, started_at, heartbeat_at)
        VALUES (%s, 'running', DATE_SUB(UTC_TIMESTAMP(), INTERVAL 20 MINUTE), UTC_TIMESTAMP())
        """,
        (user_id,)
    )
    run_a = cur.lastrowid

    # Run B: started 20 mins ago, heartbeat is stale (10 mins ago)
    cur.execute(
        """
        INSERT INTO test_runs (user_id, status, started_at, heartbeat_at)
        VALUES (%s, 'running', DATE_SUB(UTC_TIMESTAMP(), INTERVAL 20 MINUTE), DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE))
        """,
        (user_id,)
    )
    run_b = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()

    def run_heartbeat():
        for _ in range(5):
            us.update_heartbeat(run_a)
            time.sleep(0.02)

    def run_reconciliation():
        time.sleep(0.03)
        return us.reconcile_stale_reservations(timeout_minutes=5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_hb = executor.submit(run_heartbeat)
        f_rec = executor.submit(run_reconciliation)
        f_hb.result()
        reconciled_count = f_rec.result()

    assert reconciled_count >= 1

    # Check statuses
    conn = get_isolated_test_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT status FROM test_runs WHERE id = %s", (run_a,))
    status_a = cur.fetchone()["status"]

    cur.execute("SELECT status FROM test_runs WHERE id = %s", (run_b,))
    status_b = cur.fetchone()["status"]
    cur.close()
    conn.close()

    assert status_a == "running", "Active run with recent heartbeat must NOT be marked failed!"
    assert status_b == "failed", "Stale run with old heartbeat MUST be marked failed!"


# ============================================================================
# Concurrency Scenario 7: Row Lock Timeout and Rollback Safety
# ============================================================================

def test_row_lock_rollback_preserves_state(patch_db_for_test):
    """
    Demonstrate that if a transaction locks a user row and rolls back,
    another waiting thread acquires the lock cleanly and sees uncorrupted state.
    """
    user_id = create_test_user("rollback_concurrency@example.com")

    def locking_thread():
        conn1 = get_isolated_test_connection()
        cur1 = conn1.cursor()
        cur1.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        # Simulating work under lock
        time.sleep(0.5)
        conn1.rollback()
        cur1.close()
        conn1.close()

    def waiting_thread():
        # Start shortly after locking_thread
        time.sleep(0.1)
        conn2 = get_isolated_test_connection()
        cur2 = conn2.cursor(dictionary=True)
        t_start = time.time()
        cur2.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        row = cur2.fetchone()
        t_waited = time.time() - t_start
        conn2.commit()
        cur2.close()
        conn2.close()
        return row, t_waited

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(locking_thread)
        f2 = executor.submit(waiting_thread)
        f1.result()
        row, waited = f2.result()

    assert row["id"] == user_id
    assert waited >= 0.1, f"Expected second thread to wait for lock release, waited {waited:.3f}s"
