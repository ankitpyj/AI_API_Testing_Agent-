"""
Usage Management & Atomic Limit Enforcement Service.

Tracks per-user monthly usage metrics (projects, test runs, test cases, AI operations)
and enforces plan limits when ENFORCE_USAGE_LIMITS=true using atomic database locking
to prevent TOCTOU race conditions.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import hashlib
import json
import threading
from fastapi import HTTPException, status

try:
    from database import get_db_connection
    from plans import get_plan_config, is_quota_enforcement_enabled, ENFORCE_USAGE_LIMITS
except ImportError:
    from agent_backend.database import get_db_connection
    from agent_backend.plans import get_plan_config, is_quota_enforcement_enabled, ENFORCE_USAGE_LIMITS


def get_current_month_start() -> datetime:
    """
    Return datetime corresponding to midnight UTC on the first day of the current calendar month.
    Uses timezone-aware UTC for consistent boundaries across distributed servers and MySQL TIMESTAMPs.
    """
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_user_usage_metrics(user_id: int) -> Dict[str, Any]:
    """
    Calculate real database-derived usage metrics for a user:
    - total_projects: all active projects
    - total_test_runs: all-time completed test runs
    - total_test_cases: all-time executed tests
    - total_passed_tests: all-time passed tests
    - total_failed_tests: all-time failed tests
    - monthly_test_runs: completed test runs in current calendar month
    - monthly_test_cases: executed test cases in current calendar month
    - monthly_ai_operations: actual AI LLM calls logged in current month
    - last_activity: timestamp of latest test run
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Total active projects
        cursor.execute("SELECT COUNT(*) AS total FROM projects WHERE user_id = %s", (user_id,))
        total_projects = cursor.fetchone()["total"]

        # 2. All-time completed test run metrics (excluding failed/cancelled reservations)
        cursor.execute(
            """
            SELECT
                COUNT(id) AS total_runs,
                COALESCE(SUM(total_tests), 0) AS total_cases,
                COALESCE(SUM(passed_tests), 0) AS passed_cases,
                COALESCE(SUM(failed_tests), 0) AS failed_cases,
                MAX(started_at) AS last_activity
            FROM test_runs
            WHERE user_id = %s AND status NOT IN ('failed', 'cancelled')
            """,
            (user_id,)
        )
        all_time = cursor.fetchone()

        # 3. Monthly test run metrics (since 1st of current UTC month)
        month_start = get_current_month_start()
        cursor.execute(
            """
            SELECT
                COUNT(id) AS monthly_runs,
                COALESCE(SUM(total_tests), 0) AS monthly_cases
            FROM test_runs
            WHERE user_id = %s AND started_at >= %s AND status NOT IN ('failed', 'cancelled')
            """,
            (user_id, month_start)
        )
        monthly = cursor.fetchone()

        # 4. Monthly AI operations from ai_usage_logs (with fallback to test_results for legacy data)
        cursor.execute(
            """
            SELECT COUNT(id) AS monthly_ai
            FROM ai_usage_logs
            WHERE user_id = %s AND created_at >= %s AND status = 'success'
            """,
            (user_id, month_start)
        )
        ai_row = cursor.fetchone()
        monthly_ai_count = ai_row["monthly_ai"] if ai_row and ai_row.get("monthly_ai") is not None else 0

        if monthly_ai_count == 0:
            cursor.execute(
                """
                SELECT COUNT(tr.id) AS legacy_ai
                FROM test_results tr
                INNER JOIN test_runs r ON tr.run_id = r.id
                WHERE r.user_id = %s
                  AND r.started_at >= %s
                  AND (tr.category = 'AI' OR tr.test_id LIKE 'AI-%%')
                """,
                (user_id, month_start)
            )
            legacy_row = cursor.fetchone()
            if legacy_row and legacy_row.get("legacy_ai"):
                monthly_ai_count = legacy_row["legacy_ai"]

        return {
            "total_projects": total_projects,
            "total_test_runs": all_time["total_runs"],
            "total_test_cases": int(all_time["total_cases"]),
            "total_passed_tests": int(all_time["passed_cases"]),
            "total_failed_tests": int(all_time["failed_cases"]),
            "monthly_test_runs": monthly["monthly_runs"],
            "monthly_test_cases": int(monthly["monthly_cases"]),
            "monthly_ai_operations": monthly_ai_count,
            "last_activity": all_time["last_activity"].isoformat() if all_time and all_time["last_activity"] else None
        }
    finally:
        cursor.close()
        conn.close()


def check_project_limit(user_id: int, user_plan: str = "internal_demo") -> None:
    """
    Verify that creating another project will not exceed the user's plan limit.
    Enforcement occurs only when ENFORCE_USAGE_LIMITS=true.
    Handles -1 as unlimited.
    Raises HTTP 429 if the limit is reached.
    """
    if not is_quota_enforcement_enabled():
        return

    plan_cfg = get_plan_config(user_plan)
    max_allowed = plan_cfg.get("max_projects", -1)

    # Unlimited quota
    if max_allowed < 0:
        return

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM projects WHERE user_id = %s", (user_id,))
        count = cursor.fetchone()["total"]
        if count >= max_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Project limit reached ({count}/{max_allowed}) for plan '{plan_cfg['name']}'. "
                    "Upgrade your plan or delete unused projects to create more."
                )
            )
    finally:
        cursor.close()
        conn.close()


def check_test_run_limit(user_id: int, user_plan: str = "internal_demo") -> None:
    """
    Pre-check that executing another test run will not exceed the user's monthly plan limit.
    Enforcement occurs only when ENFORCE_USAGE_LIMITS=true.
    Handles -1 as unlimited.
    Raises HTTP 429 if the limit is reached.
    """
    if not is_quota_enforcement_enabled():
        return

    plan_cfg = get_plan_config(user_plan)
    max_allowed = plan_cfg.get("monthly_test_runs", -1)

    if max_allowed < 0:
        return

    month_start = get_current_month_start()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(id) AS total
            FROM test_runs
            WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s
              AND status IN ('queued', 'pending', 'running', 'completed')
            """,
            (user_id, month_start)
        )
        count = cursor.fetchone()["total"]
        if count >= max_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Monthly test run limit reached ({count}/{max_allowed}) for plan '{plan_cfg['name']}'. "
                    "Upgrade your plan to run more tests this month."
                )
            )
    finally:
        cursor.close()
        conn.close()


def reconcile_stale_reservations(timeout_minutes: int = 5) -> int:
    """
    Recover orphaned test-run reservations that were abandoned due to process crashes,
    timeouts, or ungraceful terminations.
    Marks them as 'failed' conditionally to release reserved quotas.
    Only marks runs where heartbeat_at is older than timeout_minutes (or started_at if heartbeat_at is null).
    Active runs with recent heartbeats are never marked failed regardless of total run age.
    Safe for concurrent execution across multiple server processes.
    Returns the count of reconciled stale runs.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE test_runs
            SET status = 'failed',
                estimated_tests = 0,
                completed_at = UTC_TIMESTAMP(),
                error_message = 'Execution abandoned: worker heartbeat timed out'
            WHERE status = 'running'
              AND (
                (heartbeat_at IS NOT NULL AND heartbeat_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s MINUTE))
                OR (heartbeat_at IS NULL AND started_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s MINUTE))
              )
            """,
            (timeout_minutes, timeout_minutes)
        )
        count = cursor.rowcount
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    try:
        from agent_backend import db_operations
        db_operations.reconcile_orphan_worker_slots()
    except Exception:
        pass

    return count


def update_heartbeat(run_id: int, worker_id: Optional[str] = None) -> bool:
    """
    Update the heartbeat timestamp and extend reservation_expires_at for an active test run.
    If worker_id is provided, verifies that the run is still owned by that worker.
    Also extends leased_until on worker_slots.
    Called periodically during test suite generation and execution.
    Returns True if updated, False if run was not running or worker_id ownership was lost.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if worker_id is not None:
            cursor.execute(
                """
                UPDATE test_runs
                SET heartbeat_at = UTC_TIMESTAMP(),
                    reservation_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
                WHERE id = %s AND status = 'running' AND worker_id = %s
                """,
                (run_id, worker_id)
            )
        else:
            cursor.execute(
                """
                UPDATE test_runs
                SET heartbeat_at = UTC_TIMESTAMP(),
                    reservation_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
                WHERE id = %s AND status = 'running'
                """,
                (run_id,)
            )
        try:
            ok = bool(cursor.rowcount > 0)
        except TypeError:
            ok = True
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    if ok:
        try:
            from agent_backend import db_operations
            db_operations.extend_worker_slot_lease(run_id, worker_id=worker_id)
        except Exception:
            pass

    return ok


class JobHeartbeatManager:
    """
    Continuous, periodic heartbeat runner for active background test executions.
    Runs a dedicated background daemon thread ensuring heartbeats are refreshed
    regardless of blocking network calls (e.g. Gemini LLM generation, slow target APIs).
    Fences against stale workers by verifying worker ownership on each heartbeat tick.
    """
    def __init__(self, run_id: int, worker_id: Optional[str] = None, interval_seconds: float = 30.0):
        self.run_id = run_id
        self.worker_id = worker_id
        self.interval = float(interval_seconds)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ownership_lost = False
        self._last_error: Optional[Exception] = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ownership_lost = False
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"Heartbeat-{self.run_id}-{str(self.worker_id)[:8]}",
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def is_ownership_lost(self) -> bool:
        return self._ownership_lost

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.interval):
                break
            try:
                ok = update_heartbeat(self.run_id, worker_id=self.worker_id)
                if not ok:
                    self._ownership_lost = True
                    break
            except Exception as err:
                self._last_error = err


def get_idempotent_test_run(user_id: int, idempotency_key: str) -> Optional[Dict[str, Any]]:
    """
    Look up an existing test run for the given user and idempotency key within the 24-hour window.
    Ensures strict tenant isolation: user_id is always filtered.
    """
    if not idempotency_key:
        return None
    clean_key = idempotency_key.strip()
    if not clean_key:
        return None

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, status, total_tests, passed_tests, failed_tests, started_at, created_at, project_id
            FROM test_runs
            WHERE user_id = %s AND idempotency_key = %s
              AND COALESCE(started_at, created_at) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, clean_key)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def reserve_test_run(
    user_id: int,
    project_id: Optional[int] = None,
    user_plan: str = "internal_demo",
    idempotency_key: Optional[str] = None
) -> Optional[int]:
    """
    Atomically reserve a test run slot using a MySQL transaction and exclusive user row lock
    (SELECT ... FROM users FOR UPDATE).
    
    Prevents TOCTOU race conditions where concurrent requests could bypass monthly quotas.
    Reconciles any stale reservations before checking limits.
    Tracks reservation with status='running', heartbeat_at, and optional idempotency_key.
    Raises HTTP 429 if any monthly quota (runs or AI operations) is exceeded.
    Returns the created test run ID (or existing run ID if already in progress for this key).
    """
    enforce = is_quota_enforcement_enabled()
    plan_cfg = get_plan_config(user_plan)

    clean_key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Acquire exclusive lock on the user's row in MySQL
        cursor.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            # User ID does not exist in the database (e.g., test environments with mocked auth)
            conn.rollback()
            return None

        # Clean up any stale reservations for this user under the lock
        cursor.execute(
            """
            UPDATE test_runs
            SET status = 'failed', estimated_tests = 0,
                completed_at = UTC_TIMESTAMP(),
                error_message = 'Execution abandoned: worker heartbeat timed out'
            WHERE user_id = %s
              AND status = 'running'
              AND (
                (heartbeat_at IS NOT NULL AND heartbeat_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE))
                OR (heartbeat_at IS NULL AND started_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE))
              )
            """,
            (user_id,)
        )

        # 2. Check for existing active or recent run with the same idempotency key
        if clean_key:
            cursor.execute(
                """
                SELECT id, status FROM test_runs
                WHERE user_id = %s AND idempotency_key = %s
                  AND COALESCE(started_at, created_at) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, clean_key)
            )
            existing = cursor.fetchone()
            if existing and existing["status"] in ("queued", "running", "completed"):
                conn.commit()
                return existing["id"]

        # 3. Check quota limits under the lock if enforcement is active
        if enforce:
            month_start = get_current_month_start()

            # (a) Monthly test runs check (active reservations + completed)
            max_runs = plan_cfg.get("monthly_test_runs", -1)
            if max_runs >= 0:
                cursor.execute(
                    """
                    SELECT COUNT(id) AS total_runs
                    FROM test_runs
                    WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s
                      AND status IN ('queued', 'pending', 'running', 'completed')
                    """,
                    (user_id, month_start)
                )
                active_runs = cursor.fetchone()["total_runs"]
                if active_runs >= max_runs:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly test run limit reached ({active_runs}/{max_runs}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to run more tests this month."
                        )
                    )

            # (b) Monthly test cases pre-check (completed runs + in-flight estimated tests)
            max_cases = plan_cfg.get("monthly_test_cases", -1)
            if max_cases >= 0:
                cursor.execute(
                    """
                    SELECT (
                        COALESCE((SELECT SUM(total_tests) FROM test_runs WHERE user_id = %s AND started_at >= %s AND status = 'completed'), 0) +
                        COALESCE((SELECT SUM(estimated_tests) FROM test_runs WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s AND status IN ('queued', 'running')), 0)
                    ) AS total_cases
                    """,
                    (user_id, month_start, user_id, month_start)
                )
                cases_count = int(cursor.fetchone()["total_cases"])
                if cases_count >= max_cases:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly test case limit reached ({cases_count}/{max_cases}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to execute more test cases this month."
                        )
                    )

            # (c) Monthly AI operations check (only if plan enables AI features)
            features = plan_cfg.get("features", [])
            has_ai = "ai_generation" in features or "ai_analysis" in features
            max_ai = plan_cfg.get("monthly_ai_operations", -1)
            if has_ai and max_ai >= 0:
                cursor.execute(
                    """
                    SELECT COUNT(id) AS total_ai
                    FROM ai_usage_logs
                    WHERE user_id = %s AND created_at >= %s AND (status = 'success' OR (status = 'reserved' AND created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)))
                    """,
                    (user_id, month_start)
                )
                ai_count = cursor.fetchone()["total_ai"]
                if ai_count >= max_ai:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly AI operation limit reached ({ai_count}/{max_ai}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to perform more AI operations this month."
                        )
                    )

        # 4. Create the test run reservation row with status='running', heartbeat, and expires_at
        cursor.execute(
            """
            INSERT INTO test_runs (
                user_id, project_id, status, created_at, started_at, heartbeat_at,
                reservation_expires_at, idempotency_key, total_tests, passed_tests, failed_tests, estimated_tests
            )
            VALUES (%s, %s, 'running', UTC_TIMESTAMP(), UTC_TIMESTAMP(), UTC_TIMESTAMP(), DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE), %s, 0, 0, 0, 0)
            """,
            (user_id, project_id, clean_key)
        )
        run_id = cursor.lastrowid
        conn.commit()
        return run_id
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def queue_test_run(
    user_id: int,
    project_id: Optional[int] = None,
    base_url: Optional[str] = None,
    openapi_url: Optional[str] = None,
    user_plan: str = "internal_demo",
    idempotency_key: Optional[str] = None,
    payload_hash: Optional[str] = None
) -> Optional[int]:
    """
    Atomically queue a test run for background execution under user row lock.
    Enforces monthly test-run and AI quota limits (raising HTTP 429 if exceeded).
    Validates request payload against previous idempotency submissions (raising HTTP 409 if mismatch).
    Sanitizes target URLs to prevent credential leakage.
    Sets status='queued', created_at=UTC_TIMESTAMP(), started_at=NULL, completed_at=NULL.
    Returns the created test run ID (or existing run ID if already queued/running for idempotency_key).
    """
    try:
        from db_operations import sanitize_target_url
    except ImportError:
        from agent_backend.db_operations import sanitize_target_url

    clean_base_url = sanitize_target_url(base_url)
    clean_openapi_url = sanitize_target_url(openapi_url)
    clean_key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None

    # Compute canonical payload hash if not explicitly provided
    if not payload_hash:
        payload_dict = {
            "project_id": project_id,
            "base_url": clean_base_url,
            "openapi_url": clean_openapi_url
        }
        payload_hash = hashlib.sha256(json.dumps(payload_dict, sort_keys=True).encode("utf-8")).hexdigest()

    enforce = is_quota_enforcement_enabled()
    plan_cfg = get_plan_config(user_plan)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Acquire exclusive lock on the user's row
        cursor.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.rollback()
            return None

        # Clean up stale reservations
        cursor.execute(
            """
            UPDATE test_runs
            SET status = 'failed', estimated_tests = 0,
                completed_at = UTC_TIMESTAMP(),
                error_message = 'Execution abandoned: worker heartbeat timed out'
            WHERE user_id = %s
              AND status = 'running'
              AND (
                (heartbeat_at IS NOT NULL AND heartbeat_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE))
                OR (heartbeat_at IS NULL AND started_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE))
              )
            """,
            (user_id,)
        )

        # Idempotency check: if already queued, running, or completed within 24h
        if clean_key:
            cursor.execute(
                """
                SELECT id, status, payload_hash FROM test_runs
                WHERE user_id = %s AND idempotency_key = %s
                  AND COALESCE(started_at, created_at) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, clean_key)
            )
            existing = cursor.fetchone()
            if existing:
                # If same idempotency key is submitted with different payload, raise 409 Conflict
                if existing.get("payload_hash") and existing["payload_hash"] != payload_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key reuse with different request payload."
                    )
                if existing["status"] in ("queued", "running", "completed"):
                    conn.commit()
                    return existing["id"]

        # Quota checks under lock
        if enforce:
            month_start = get_current_month_start()
            max_runs = plan_cfg.get("monthly_test_runs", -1)
            if max_runs >= 0:
                cursor.execute(
                    """
                    SELECT COUNT(id) AS total_runs
                    FROM test_runs
                    WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s
                      AND status IN ('queued', 'pending', 'running', 'completed')
                    """,
                    (user_id, month_start)
                )
                active_runs = cursor.fetchone()["total_runs"]
                if active_runs >= max_runs:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly test run limit reached ({active_runs}/{max_runs}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to run more tests this month."
                        )
                    )

            max_cases = plan_cfg.get("monthly_test_cases", -1)
            if max_cases >= 0:
                cursor.execute(
                    """
                    SELECT (
                        COALESCE((SELECT SUM(total_tests) FROM test_runs WHERE user_id = %s AND started_at >= %s AND status = 'completed'), 0) +
                        COALESCE((SELECT SUM(estimated_tests) FROM test_runs WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s AND status IN ('queued', 'running')), 0)
                    ) AS total_cases
                    """,
                    (user_id, month_start, user_id, month_start)
                )
                cases_count = int(cursor.fetchone()["total_cases"])
                if cases_count >= max_cases:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly test case limit reached ({cases_count}/{max_cases}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to execute more test cases this month."
                        )
                    )

            features = plan_cfg.get("features", [])
            has_ai = "ai_generation" in features or "ai_analysis" in features
            max_ai = plan_cfg.get("monthly_ai_operations", -1)
            if has_ai and max_ai >= 0:
                cursor.execute(
                    """
                    SELECT COUNT(id) AS total_ai
                    FROM ai_usage_logs
                    WHERE user_id = %s AND created_at >= %s AND (status = 'success' OR (status = 'reserved' AND created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)))
                    """,
                    (user_id, month_start)
                )
                ai_count = cursor.fetchone()["total_ai"]
                if ai_count >= max_ai:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Monthly AI operation limit reached ({ai_count}/{max_ai}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan to perform more AI operations this month."
                        )
                    )

        # Insert test run in 'queued' status
        cursor.execute(
            """
            INSERT INTO test_runs (
                user_id, project_id, status, created_at, started_at, completed_at,
                base_url, openapi_url, heartbeat_at, reservation_expires_at,
                idempotency_key, payload_hash, total_tests, passed_tests, failed_tests, estimated_tests
            )
            VALUES (%s, %s, 'queued', UTC_TIMESTAMP(), NULL, NULL, %s, %s, UTC_TIMESTAMP(), DATE_ADD(UTC_TIMESTAMP(), INTERVAL 15 MINUTE), %s, %s, 0, 0, 0, 0)
            """,
            (user_id, project_id, clean_base_url, clean_openapi_url, clean_key, payload_hash)
        )
        run_id = cursor.lastrowid
        conn.commit()
        return run_id
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def reserve_test_case_quota(
    user_id: int,
    run_id: int,
    estimated_tests: int,
    user_plan: str = "internal_demo"
) -> int:
    """
    Transactionally reserve estimated test cases for an in-flight test run.
    Checks remaining allowance against:
      - completed test cases (status = 'completed')
      - in-flight estimated test cases of other concurrent runs (status = 'running' AND id != run_id)
    If estimated_tests > remaining allowance, raises HTTP 429 before test execution.
    Updates test_runs.estimated_tests for the run_id.
    Returns the remaining test case budget (or -1 if unlimited).
    """
    if not is_quota_enforcement_enabled():
        return -1

    plan_cfg = get_plan_config(user_plan)
    max_cases = plan_cfg.get("monthly_test_cases", -1)
    if max_cases < 0:
        return -1

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Acquire lock on the user's row
        cursor.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.rollback()
            return -1

        month_start = get_current_month_start()

        # Count completed test cases
        cursor.execute(
            """
            SELECT COALESCE(SUM(total_tests), 0) AS completed_cases
            FROM test_runs
            WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s AND status = 'completed'
            """,
            (user_id, month_start)
        )
        completed_cases = int(cursor.fetchone()["completed_cases"])

        # Count in-flight estimated test cases from other active runs (queued or running)
        cursor.execute(
            """
            SELECT COALESCE(SUM(estimated_tests), 0) AS in_flight_cases
            FROM test_runs
            WHERE user_id = %s AND COALESCE(started_at, created_at) >= %s
              AND status IN ('queued', 'running') AND id != %s
            """,
            (user_id, month_start, run_id)
        )
        in_flight_cases = int(cursor.fetchone()["in_flight_cases"])

        total_consumed = completed_cases + in_flight_cases
        remaining_budget = max(0, max_cases - total_consumed)

        if estimated_tests > remaining_budget:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Monthly test case limit exceeded for plan '{plan_cfg['name']}'. "
                    f"Estimated {estimated_tests} test cases exceeds remaining allowance of "
                    f"{remaining_budget} (limit: {max_cases}, completed: {completed_cases}, "
                    f"in-flight: {in_flight_cases})."
                )
            )

        # Allocate reservation on the run
        cursor.execute(
            """
            UPDATE test_runs
            SET estimated_tests = %s,
                heartbeat_at = UTC_TIMESTAMP(),
                reservation_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
            WHERE id = %s
            """,
            (estimated_tests, run_id)
        )
        conn.commit()
        return remaining_budget
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def reserve_ai_operation(
    user_id: int,
    run_id: Optional[int] = None,
    call_type: str = "generation",
    model: str = "gemini-flash-lite-latest",
    user_plan: Optional[str] = None
) -> Optional[int]:
    """
    Atomically reserve a single AI operation slot immediately before making an outbound LLM call.
    Checks remaining monthly AI quota under user row lock.
    Inserts a row into ai_usage_logs with status='reserved'.
    Commits immediately so NO MySQL transaction is held open during the LLM network call.
    Returns the log_id, or None if quota is exhausted.
    """
    enforce = is_quota_enforcement_enabled()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if enforce:
            cursor.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
            user_row = cursor.fetchone()
            if not user_row:
                conn.rollback()
                return None

            plan_name = user_plan or user_row.get("plan", "internal_demo")
            plan_cfg = get_plan_config(plan_name)
            max_ai = plan_cfg.get("monthly_ai_operations", -1)

            if max_ai >= 0:
                month_start = get_current_month_start()
                cursor.execute(
                    """
                    SELECT COUNT(id) AS total_ai
                    FROM ai_usage_logs
                    WHERE user_id = %s AND created_at >= %s
                      AND (status = 'success' OR (status = 'reserved' AND created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)))
                    """,
                    (user_id, month_start)
                )
                ai_count = cursor.fetchone()["total_ai"]
                if ai_count >= max_ai:
                    conn.rollback()
                    return None

        cursor.execute(
            """
            INSERT INTO ai_usage_logs (user_id, run_id, call_type, provider, model, status, created_at)
            VALUES (%s, %s, %s, 'gemini', %s, 'reserved', UTC_TIMESTAMP())
            """,
            (user_id, run_id, call_type, model)
        )
        log_id = cursor.lastrowid
        conn.commit()
        return log_id
    except Exception:
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()


def complete_ai_operation(
    log_id: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0
) -> None:
    """
    Transition a reserved AI operation to 'success' status with recorded token usage.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE ai_usage_logs
            SET status = 'success', input_tokens = %s, output_tokens = %s, total_tokens = %s
            WHERE id = %s
            """,
            (input_tokens, output_tokens, total_tokens, log_id)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def fail_ai_operation(log_id: int) -> None:
    """
    Transition a reserved AI operation to 'failed' status so it does not count against quota.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE ai_usage_logs SET status = 'failed' WHERE id = %s",
            (log_id,)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def complete_test_run(
    run_id: int,
    total_tests: int,
    passed_tests: int,
    failed_tests: int,
    worker_id: Optional[str] = None
) -> bool:
    """
    Transition a running test run to 'completed' status and persist executed test counts.
    Records completed_at = UTC_TIMESTAMP() and releases worker_slot.
    If worker_id is supplied, verifies that the worker still owns the job.
    Conditional update ensures cancelled, failed, or reclaimed runs cannot accidentally be completed.
    Returns True if transitioned, False if run was not in 'running' state or worker_id did not match.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if worker_id is not None:
            cursor.execute(
                """
                UPDATE test_runs
                SET total_tests = %s, passed_tests = %s, failed_tests = %s,
                    estimated_tests = 0, status = 'completed',
                    completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP()
                WHERE id = %s AND status = 'running' AND worker_id = %s
                """,
                (total_tests, passed_tests, failed_tests, run_id, worker_id)
            )
        else:
            cursor.execute(
                """
                UPDATE test_runs
                SET total_tests = %s, passed_tests = %s, failed_tests = %s,
                    estimated_tests = 0, status = 'completed',
                    completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP()
                WHERE id = %s AND status = 'running'
                """,
                (total_tests, passed_tests, failed_tests, run_id)
            )
        try:
            ok = bool(cursor.rowcount > 0)
        except TypeError:
            ok = True
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    if ok:
        try:
            from agent_backend import db_operations
            db_operations.release_worker_slot(run_id, worker_id=worker_id)
        except Exception:
            pass

    return ok


def fail_test_run(
    run_id: int,
    error_message: Optional[str] = None,
    worker_id: Optional[str] = None
) -> bool:
    """
    Transition a test run to 'failed' status when execution encounters an error.
    Accepts jobs in 'queued' or 'running' states.
    If worker_id is provided, verifies ownership so stale workers cannot fail runs owned by newer workers.
    Frees the quota reservation (estimated_tests=0), releases worker slot, and records completed_at and sanitized error_message.
    Conditional update ensures completed runs cannot become failed by a late worker update.
    Returns True if transitioned, False otherwise.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if error_message is not None:
            try:
                from engine.authentication.response_sanitizer import sanitize_error_message
            except ImportError:
                from agent_backend.engine.authentication.response_sanitizer import sanitize_error_message
            clean_msg = sanitize_error_message(error_message, max_length=1000)
            if worker_id is not None:
                cursor.execute(
                    """
                    UPDATE test_runs
                    SET status = 'failed', estimated_tests = 0,
                        completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP(),
                        error_message = %s
                    WHERE id = %s AND status IN ('queued', 'running') AND (worker_id = %s OR worker_id IS NULL)
                    """,
                    (clean_msg, run_id, worker_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE test_runs
                    SET status = 'failed', estimated_tests = 0,
                        completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP(),
                        error_message = %s
                    WHERE id = %s AND status IN ('queued', 'running')
                    """,
                    (clean_msg, run_id)
                )
        else:
            if worker_id is not None:
                cursor.execute(
                    """
                    UPDATE test_runs
                    SET status = 'failed', estimated_tests = 0,
                        completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP()
                    WHERE id = %s AND status IN ('queued', 'running') AND (worker_id = %s OR worker_id IS NULL)
                    """,
                    (run_id, worker_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE test_runs
                    SET status = 'failed', estimated_tests = 0,
                        completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP()
                    WHERE id = %s AND status IN ('queued', 'running')
                    """,
                    (run_id,)
                )
        try:
            ok = bool(cursor.rowcount > 0)
        except TypeError:
            ok = True
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    if ok:
        try:
            from agent_backend import db_operations
            db_operations.release_worker_slot(run_id, worker_id=worker_id)
        except Exception:
            pass

    return ok


def cancel_test_run(run_id: int, user_id: Optional[int] = None) -> bool:
    """
    Transition a test run to 'cancelled' status.
    Accepts jobs in 'queued' or 'running' states.
    Frees the quota reservation, releases worker slot, and records completed_at.
    Enforces tenant isolation if user_id is provided.
    Conditional update ensures completed or failed runs cannot be cancelled.
    Returns True if transitioned, False otherwise.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if user_id is not None:
            cursor.execute(
                """
                UPDATE test_runs
                SET status = 'cancelled', estimated_tests = 0,
                    completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP(),
                    error_message = 'Cancelled by user'
                WHERE id = %s AND user_id = %s AND status IN ('queued', 'running')
                """,
                (run_id, user_id)
            )
        else:
            cursor.execute(
                """
                UPDATE test_runs
                SET status = 'cancelled', estimated_tests = 0,
                    completed_at = UTC_TIMESTAMP(), heartbeat_at = UTC_TIMESTAMP(),
                    error_message = 'Cancelled by user'
                WHERE id = %s AND status IN ('queued', 'running')
                """,
                (run_id,)
            )
        try:
            ok = bool(cursor.rowcount > 0)
        except TypeError:
            ok = True
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    try:
        from agent_backend import db_operations
        db_operations.release_worker_slot(run_id)
    except Exception:
        pass

    return ok
