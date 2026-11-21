"""
Internal Admin Dashboard API Routes.

Provides administrator-only endpoints for platform governance, user management,
and telemetry.
Strictly protected by get_current_admin (requires verified JWT and role == 'admin').
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from auth import get_current_admin
    from database import get_db_connection
    from plans import (
        PLATFORM_MODE,
        ENFORCE_USAGE_LIMITS,
        PLAN_DEFINITIONS,
        get_platform_mode,
        is_quota_enforcement_enabled,
    )
except ImportError:
    from agent_backend.auth import get_current_admin
    from agent_backend.database import get_db_connection
    from agent_backend.plans import (
        PLATFORM_MODE,
        ENFORCE_USAGE_LIMITS,
        PLAN_DEFINITIONS,
        get_platform_mode,
        is_quota_enforcement_enabled,
    )


router = APIRouter(prefix="/admin", tags=["admin"])


# ===========================================================================
# 1. Platform Overview
# ===========================================================================

@router.get("/overview")
def get_admin_overview(
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Return high-level platform-wide administration telemetry.
    Restricted to verified administrators.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Total registered users
        cursor.execute("SELECT COUNT(*) AS total FROM users")
        total_users = cursor.fetchone()["total"]

        # 2. Active users (distinct users who executed a test run in the last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        cursor.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS active_total
            FROM test_runs
            WHERE user_id IS NOT NULL AND started_at >= %s
            """,
            (thirty_days_ago,)
        )
        active_users = cursor.fetchone()["active_total"]

        # 3. Total projects
        cursor.execute("SELECT COUNT(*) AS total FROM projects")
        total_projects = cursor.fetchone()["total"]

        # 4. Total test runs, test cases, and pass/fail breakdown
        cursor.execute(
            """
            SELECT
                COUNT(id) AS total_runs,
                COALESCE(SUM(total_tests), 0) AS total_cases,
                COALESCE(SUM(passed_tests), 0) AS passed_cases,
                COALESCE(SUM(failed_tests), 0) AS failed_cases
            FROM test_runs
            """
        )
        run_stats = cursor.fetchone()

        total_runs = run_stats["total_runs"]
        total_cases = int(run_stats["total_cases"])
        passed_cases = int(run_stats["passed_cases"])
        failed_cases = int(run_stats["failed_cases"])
        overall_pass_rate = (
            round((passed_cases / total_cases) * 100, 2)
            if total_cases > 0
            else 0.0
        )

        # 5. Recent registrations (latest 5 users)
        cursor.execute(
            """
            SELECT id, full_name, email, role, plan, created_at
            FROM users
            ORDER BY id DESC
            LIMIT 5
            """
        )
        recent_users_raw = cursor.fetchall()
        recent_registrations = []
        for u in recent_users_raw:
            recent_registrations.append({
                "id": u["id"],
                "full_name": u["full_name"],
                "email": u["email"],
                "role": u.get("role", "user"),
                "plan": u.get("plan", "internal_demo"),
                "created_at": u["created_at"].isoformat() if u["created_at"] else None
            })

        # 6. Recent platform activity (latest 5 test runs across all users)
        cursor.execute(
            """
            SELECT
                tr.id AS run_id,
                tr.user_id,
                COALESCE(p.project_name, 'Standalone API') AS project_name,
                tr.total_tests,
                tr.passed_tests,
                tr.failed_tests,
                tr.started_at AS created_at,
                CASE
                    WHEN tr.failed_tests = 0 AND tr.total_tests > 0 THEN 'PASS'
                    WHEN tr.failed_tests > 0 THEN 'FAIL'
                    ELSE 'EMPTY'
                END AS status
            FROM test_runs tr
            LEFT JOIN projects p ON tr.project_id = p.id
            ORDER BY tr.id DESC
            LIMIT 5
            """
        )
        recent_runs_raw = cursor.fetchall()
        recent_activity = []
        for r in recent_runs_raw:
            recent_activity.append({
                "run_id": r["run_id"],
                "user_id": r["user_id"],
                "project_name": r["project_name"],
                "total_tests": r["total_tests"],
                "passed_tests": r["passed_tests"],
                "failed_tests": r["failed_tests"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None
            })

        return {
            "platform_mode": get_platform_mode(),
            "enforce_usage_limits": is_quota_enforcement_enabled(),
            "total_users": total_users,
            "active_users": active_users,
            "total_projects": total_projects,
            "total_test_runs": total_runs,
            "total_test_cases": total_cases,
            "total_passed_tests": passed_cases,
            "total_failed_tests": failed_cases,
            "overall_pass_percentage": overall_pass_rate,
            "recent_registrations": recent_registrations,
            "recent_activity": recent_activity
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 2. User Management Listing
# ===========================================================================

@router.get("/users")
def get_admin_users(
    limit: int = Query(10, ge=1, le=100, description="Users per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    search: Optional[str] = Query(None, description="Search by email or name"),
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Return paginated user list with project count, test run count, and last active timestamp.
    Does not expose password hashes or sensitive authentication data.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        where_clause = ""
        params: List[Any] = []
        if search and search.strip():
            where_clause = "WHERE LOWER(u.email) LIKE %s OR LOWER(u.full_name) LIKE %s"
            term = f"%{search.strip().lower()}%"
            params.extend([term, term])

        # 1. Total matching count
        count_sql = f"SELECT COUNT(*) AS total FROM users u {where_clause}"
        cursor.execute(count_sql, tuple(params))
        total_count = cursor.fetchone()["total"]

        # 2. Paginated rows with aggregates (avoiding N+1 queries)
        query = f"""
            SELECT
                u.id,
                u.full_name,
                u.email,
                u.role,
                u.plan,
                u.created_at,
                COUNT(DISTINCT p.id) AS project_count,
                COUNT(DISTINCT tr.id) AS test_run_count,
                MAX(tr.started_at) AS last_activity
            FROM users u
            LEFT JOIN projects p ON p.user_id = u.id
            LEFT JOIN test_runs tr ON tr.user_id = u.id
            {where_clause}
            GROUP BY u.id, u.full_name, u.email, u.role, u.plan, u.created_at
            ORDER BY u.id DESC
            LIMIT %s OFFSET %s
        """
        fetch_params = list(params) + [limit, offset]
        cursor.execute(query, tuple(fetch_params))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "full_name": r["full_name"],
                "email": r["email"],
                "role": r.get("role", "user"),
                "plan": r.get("plan", "internal_demo"),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "project_count": r["project_count"],
                "test_run_count": r["test_run_count"],
                "last_activity": r["last_activity"].isoformat() if r["last_activity"] else None
            })

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "items": items
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 3. Individual User Details
# ===========================================================================

@router.get("/users/{user_id}")
def get_admin_user_detail(
    user_id: int,
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Return comprehensive profile and usage metrics for a specific user.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, full_name, email, role, plan, created_at, updated_at
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found."
            )

        # Usage summary
        cursor.execute(
            """
            SELECT
                COUNT(id) AS total_runs,
                COALESCE(SUM(total_tests), 0) AS total_tests,
                COALESCE(SUM(passed_tests), 0) AS passed_tests,
                COALESCE(SUM(failed_tests), 0) AS failed_tests,
                MAX(started_at) AS last_activity
            FROM test_runs
            WHERE user_id = %s
            """,
            (user_id,)
        )
        run_stats = cursor.fetchone()

        total_runs = run_stats["total_runs"]
        total_tests = int(run_stats["total_tests"])
        passed = int(run_stats["passed_tests"])
        failed = int(run_stats["failed_tests"])
        pass_rate = round((passed / total_tests) * 100, 2) if total_tests > 0 else 0.0

        # User's projects
        cursor.execute(
            """
            SELECT
                p.id,
                p.project_name,
                p.base_url,
                p.auth_type,
                p.created_at,
                COUNT(tr.id) AS run_count
            FROM projects p
            LEFT JOIN test_runs tr ON tr.project_id = p.id
            WHERE p.user_id = %s
            GROUP BY p.id, p.project_name, p.base_url, p.auth_type, p.created_at
            ORDER BY p.id DESC
            """,
            (user_id,)
        )
        projects_raw = cursor.fetchall()
        user_projects = []
        for p in projects_raw:
            user_projects.append({
                "id": p["id"],
                "project_name": p["project_name"],
                "base_url": p["base_url"],
                "auth_type": p["auth_type"],
                "created_at": p["created_at"].isoformat() if p["created_at"] else None,
                "run_count": p["run_count"]
            })

        return {
            "user": {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"],
                "role": user.get("role", "user"),
                "plan": user.get("plan", "internal_demo"),
                "created_at": user["created_at"].isoformat() if user["created_at"] else None,
            },
            "usage": {
                "total_projects": len(user_projects),
                "total_runs": total_runs,
                "total_tests": total_tests,
                "passed_tests": passed,
                "failed_tests": failed,
                "pass_percentage": pass_rate,
                "last_activity": run_stats["last_activity"].isoformat() if run_stats["last_activity"] else None,
            },
            "projects": user_projects
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 4. Platform-Wide Usage & Plan Distribution
# ===========================================================================

@router.get("/usage")
def get_admin_usage_telemetry(
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Return platform-wide usage metrics, plan distributions, and AI execution counts.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Plan distribution
        cursor.execute("SELECT plan, COUNT(*) AS user_count FROM users GROUP BY plan")
        plan_rows = cursor.fetchall()
        plan_distribution = {r["plan"]: r["user_count"] for r in plan_rows}

        # Platform metrics
        cursor.execute("SELECT COUNT(*) AS total_projects FROM projects")
        total_projects = cursor.fetchone()["total_projects"]

        cursor.execute(
            """
            SELECT
                COUNT(id) AS total_runs,
                COALESCE(SUM(total_tests), 0) AS total_cases,
                COALESCE(SUM(passed_tests), 0) AS passed_cases,
                COALESCE(SUM(failed_tests), 0) AS failed_cases
            FROM test_runs
            """
        )
        runs_data = cursor.fetchone()

        # AI operations count from ai_usage_logs (with fallback to test_results for legacy data)
        cursor.execute("SELECT COUNT(id) AS total_ai_operations FROM ai_usage_logs WHERE status = 'success'")
        ai_ops_row = cursor.fetchone()
        ai_ops = ai_ops_row["total_ai_operations"] if ai_ops_row and ai_ops_row.get("total_ai_operations") else 0
        if ai_ops == 0:
            cursor.execute(
                """
                SELECT COUNT(id) AS total_legacy_ai
                FROM test_results
                WHERE category = 'AI' OR test_id LIKE 'AI-%%'
                """
            )
            legacy_ai_row = cursor.fetchone()
            if legacy_ai_row and legacy_ai_row.get("total_legacy_ai"):
                ai_ops = legacy_ai_row["total_legacy_ai"]

        return {
            "platform_mode": get_platform_mode(),
            "enforce_usage_limits": is_quota_enforcement_enabled(),
            "plan_distribution": plan_distribution,
            "total_projects": total_projects,
            "total_test_runs": runs_data["total_runs"],
            "total_test_cases": int(runs_data["total_cases"]),
            "total_passed_tests": int(runs_data["passed_cases"]),
            "total_failed_tests": int(runs_data["failed_cases"]),
            "total_ai_operations": ai_ops,
            "available_plans": PLAN_DEFINITIONS
        }
    finally:
        cursor.close()
        conn.close()


@router.get("/worker-metrics")
def get_admin_worker_metrics(
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Return operational background worker metrics, queue depth, and slot utilization.
    Restricted to verified administrators.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Worker slots status
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_slots,
                SUM(CASE WHEN run_id IS NOT NULL AND leased_until > UTC_TIMESTAMP() THEN 1 ELSE 0 END) AS active_slots,
                SUM(CASE WHEN run_id IS NULL OR leased_until <= UTC_TIMESTAMP() THEN 1 ELSE 0 END) AS available_slots
            FROM worker_slots
            """
        )
        slots_row = cursor.fetchone() or {"total_slots": 0, "active_slots": 0, "available_slots": 0}

        # 2. Queue depth & running jobs
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_jobs,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs
            FROM test_runs
            """
        )
        queue_row = cursor.fetchone() or {"queued_jobs": 0, "running_jobs": 0}

        # 3. 24-hour job outcome breakdown
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_24h,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_24h,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_24h,
                AVG(CASE WHEN status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
                         THEN TIMESTAMPDIFF(SECOND, started_at, completed_at) ELSE NULL END) AS avg_duration_seconds
            FROM test_runs
            WHERE created_at >= %s
            """,
            (twenty_four_hours_ago,)
        )
        outcome_row = cursor.fetchone() or {}

        return {
            "status": "healthy" if int(slots_row.get("available_slots") or 0) > 0 or int(queue_row.get("queued_jobs") or 0) < 50 else "degraded",
            "slots": {
                "total": int(slots_row.get("total_slots") or 0),
                "active": int(slots_row.get("active_slots") or 0),
                "available": int(slots_row.get("available_slots") or 0),
                "utilization_percent": round(
                    (int(slots_row.get("active_slots") or 0) / max(int(slots_row.get("total_slots") or 1), 1)) * 100, 1
                ),
            },
            "queue": {
                "depth": int(queue_row.get("queued_jobs") or 0),
                "running": int(queue_row.get("running_jobs") or 0),
            },
            "recent_24h": {
                "completed": int(outcome_row.get("completed_24h") or 0),
                "failed": int(outcome_row.get("failed_24h") or 0),
                "cancelled": int(outcome_row.get("cancelled_24h") or 0),
                "avg_duration_seconds": round(float(outcome_row.get("avg_duration_seconds") or 0), 1),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        cursor.close()
        conn.close()
