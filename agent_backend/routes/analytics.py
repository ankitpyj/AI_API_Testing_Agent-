"""
Analytics and Usage Monitoring Routes for AI API Testing Agent SaaS.

Provides authenticated endpoints for:
- GET /analytics/overview
- GET /analytics/test-trends
- GET /analytics/project-performance
- GET /analytics/bug-summary
- GET /analytics/recent-activity

Strictly enforces:
- JWT authentication via get_current_user dependency.
- Multi-user data isolation (User A cannot see User B's statistics or projects).
- Exclusion of legacy unowned test runs (user_id IS NULL).
- Verification of project ownership on all project filters (returns 404 for inaccessible projects).
- SQL parameterized queries and database-side aggregation.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from auth import get_current_user
    from database import get_db_connection
except ImportError:
    from agent_backend.auth import get_current_user
    from agent_backend.database import get_db_connection


router = APIRouter(prefix="/analytics", tags=["analytics"])


def _verify_project_ownership(project_id: int, user_id: int, cursor) -> Dict[str, Any]:
    """
    Verify that the specified project belongs to the authenticated user.
    Raises 404 if project doesn't exist or is not owned by user.
    """
    cursor.execute(
        "SELECT id, project_name FROM projects WHERE id = %s AND user_id = %s",
        (project_id, user_id)
    )
    proj = cursor.fetchone()
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found or you do not have access to it."
        )
    return proj


def _resolve_date_range(
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Tuple[Optional[date], Optional[date]]:
    """
    Parse and validate date range filters.
    Returns (start_date, end_date) as datetime.date objects or (None, None).
    """
    today = date.today()

    if start_date or end_date:
        try:
            start_d = date.fromisoformat(start_date.strip()[:10]) if start_date else None
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid start_date format '{start_date}'. Expected YYYY-MM-DD."
            )
        try:
            end_d = date.fromisoformat(end_date.strip()[:10]) if end_date else today
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid end_date format '{end_date}'. Expected YYYY-MM-DD."
            )
        if start_d and end_d and start_d > end_d:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date cannot be after end_date."
            )
        return start_d, end_d

    if days is not None:
        if days < 1 or days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="days must be between 1 and 365."
            )
        start_d = today - timedelta(days=days - 1)
        return start_d, today

    return None, None


# ===========================================================================
# 1. Overview Analytics
# ===========================================================================

@router.get("/overview")
def get_analytics_overview(
    project_id: Optional[int] = Query(None, description="Optional project filter"),
    days: Optional[int] = Query(None, description="Filter to last N days"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Return high-level summary KPIs and usage monitoring metrics for the authenticated user.
    Only includes projects, test runs, and bug reports owned by current_user.
    """
    user_id = current_user["id"]
    start_d, end_d = _resolve_date_range(days=days, start_date=start_date, end_date=end_date)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if project_id is not None:
            _verify_project_ownership(project_id, user_id, cursor)

        # 1. Total projects count
        if project_id is not None:
            total_projects = 1
        else:
            cursor.execute("SELECT COUNT(*) AS total FROM projects WHERE user_id = %s", (user_id,))
            total_projects = cursor.fetchone()["total"]

        # 2. Test runs & test cases aggregation
        run_query = """
            SELECT
                COUNT(id) AS total_test_runs,
                COALESCE(SUM(total_tests), 0) AS total_test_cases,
                COALESCE(SUM(passed_tests), 0) AS total_passed_tests,
                COALESCE(SUM(failed_tests), 0) AS total_failed_tests,
                MAX(started_at) AS last_activity
            FROM test_runs
            WHERE user_id = %s
        """
        run_params: List[Any] = [user_id]

        if project_id is not None:
            run_query += " AND project_id = %s"
            run_params.append(project_id)
        if start_d is not None:
            run_query += " AND started_at >= %s"
            run_params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            run_query += " AND started_at <= %s"
            run_params.append(datetime.combine(end_d, datetime.max.time()))

        cursor.execute(run_query, tuple(run_params))
        run_stats = cursor.fetchone()

        total_test_runs = run_stats["total_test_runs"]
        total_test_cases = int(run_stats["total_test_cases"])
        total_passed_tests = int(run_stats["total_passed_tests"])
        total_failed_tests = int(run_stats["total_failed_tests"])
        last_activity = run_stats["last_activity"].isoformat() if run_stats["last_activity"] else None

        pass_percentage = (
            round((total_passed_tests / total_test_cases) * 100, 2)
            if total_test_cases > 0
            else 0.0
        )

        # 3. Bug reports aggregation
        bug_query = """
            SELECT
                COUNT(b.id) AS total_bug_reports,
                COALESCE(SUM(CASE WHEN LOWER(b.status) = 'open' THEN 1 ELSE 0 END), 0) AS open_bug_reports
            FROM bug_reports b
            INNER JOIN test_runs tr ON b.run_id = tr.id
            WHERE tr.user_id = %s
        """
        bug_params: List[Any] = [user_id]

        if project_id is not None:
            bug_query += " AND tr.project_id = %s"
            bug_params.append(project_id)
        if start_d is not None:
            bug_query += " AND tr.started_at >= %s"
            bug_params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            bug_query += " AND tr.started_at <= %s"
            bug_params.append(datetime.combine(end_d, datetime.max.time()))

        cursor.execute(bug_query, tuple(bug_params))
        bug_stats = cursor.fetchone()

        total_bug_reports = bug_stats["total_bug_reports"]
        open_bug_reports = int(bug_stats["open_bug_reports"])

        return {
            "total_projects": total_projects,
            "total_test_runs": total_test_runs,
            "total_test_cases": total_test_cases,
            "total_passed_tests": total_passed_tests,
            "total_failed_tests": total_failed_tests,
            "pass_percentage": pass_percentage,
            "total_bug_reports": total_bug_reports,
            "open_bug_reports": open_bug_reports,
            "usage": {
                "total_runs": total_test_runs,
                "total_test_cases": total_test_cases,
                "total_projects": total_projects,
                "last_activity": last_activity,
            }
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 2. Test Execution Trends
# ===========================================================================

@router.get("/test-trends")
def get_test_trends(
    days: int = Query(7, description="Number of days to analyze (e.g. 7, 30, 90)"),
    project_id: Optional[int] = Query(None, description="Optional project filter"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Return test execution trend metrics aggregated by calendar day.
    Fills in zero-activity dates so charts have continuous timelines.
    """
    user_id = current_user["id"]
    start_d, end_d = _resolve_date_range(days=days, start_date=start_date, end_date=end_date)
    if start_d is None or end_d is None:
        end_d = date.today()
        start_d = end_d - timedelta(days=6)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if project_id is not None:
            _verify_project_ownership(project_id, user_id, cursor)

        query = """
            SELECT
                DATE(started_at) AS run_date,
                COUNT(id) AS total_runs,
                COALESCE(SUM(total_tests), 0) AS total_tests,
                COALESCE(SUM(passed_tests), 0) AS passed_tests,
                COALESCE(SUM(failed_tests), 0) AS failed_tests
            FROM test_runs
            WHERE user_id = %s
              AND started_at >= %s
              AND started_at <= %s
        """
        params: List[Any] = [
            user_id,
            datetime.combine(start_d, datetime.min.time()),
            datetime.combine(end_d, datetime.max.time()),
        ]

        if project_id is not None:
            query += " AND project_id = %s"
            params.append(project_id)

        query += " GROUP BY DATE(started_at) ORDER BY run_date ASC"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        # Map by date string YYYY-MM-DD
        db_data = {}
        for r in rows:
            date_key = r["run_date"].strftime("%Y-%m-%d") if hasattr(r["run_date"], "strftime") else str(r["run_date"])
            db_data[date_key] = {
                "total_runs": r["total_runs"],
                "total_tests": int(r["total_tests"]),
                "passed_tests": int(r["passed_tests"]),
                "failed_tests": int(r["failed_tests"]),
            }

        # Generate zero-activity timeline across the entire date window
        trend_items = []
        curr = start_d
        while curr <= end_d:
            d_str = curr.strftime("%Y-%m-%d")
            stat = db_data.get(d_str, {"total_runs": 0, "total_tests": 0, "passed_tests": 0, "failed_tests": 0})
            total = stat["total_tests"]
            passed = stat["passed_tests"]
            rate = round((passed / total) * 100, 2) if total > 0 else 0.0

            trend_items.append({
                "date": d_str,
                "total_runs": stat["total_runs"],
                "total_tests": total,
                "passed_tests": passed,
                "failed_tests": stat["failed_tests"],
                "pass_percentage": rate,
            })
            curr += timedelta(days=1)

        return {
            "days": (end_d - start_d).days + 1,
            "start_date": start_d.strftime("%Y-%m-%d"),
            "end_date": end_d.strftime("%Y-%m-%d"),
            "trends": trend_items
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 3. Project Performance
# ===========================================================================

@router.get("/project-performance")
def get_project_performance(
    project_id: Optional[int] = Query(None, description="Optional single project filter"),
    days: Optional[int] = Query(None, description="Filter to last N days"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Return project-level test statistics for all projects owned by the user.
    """
    user_id = current_user["id"]
    start_d, end_d = _resolve_date_range(days=days, start_date=start_date, end_date=end_date)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if project_id is not None:
            _verify_project_ownership(project_id, user_id, cursor)

        query = """
            SELECT
                p.id AS project_id,
                p.project_name,
                COUNT(tr.id) AS total_runs,
                COALESCE(SUM(tr.total_tests), 0) AS total_tests,
                COALESCE(SUM(tr.passed_tests), 0) AS passed_tests,
                COALESCE(SUM(tr.failed_tests), 0) AS failed_tests
            FROM projects p
            LEFT JOIN test_runs tr
                ON tr.project_id = p.id
                AND tr.user_id = %s
        """
        params: List[Any] = [user_id]

        if start_d is not None:
            query += " AND tr.started_at >= %s"
            params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            query += " AND tr.started_at <= %s"
            params.append(datetime.combine(end_d, datetime.max.time()))

        query += " WHERE p.user_id = %s"
        params.append(user_id)

        if project_id is not None:
            query += " AND p.id = %s"
            params.append(project_id)

        query += " GROUP BY p.id, p.project_name ORDER BY total_runs DESC, p.project_name ASC"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            tot = int(r["total_tests"])
            passed = int(r["passed_tests"])
            rate = round((passed / tot) * 100, 2) if tot > 0 else 0.0

            items.append({
                "project_id": r["project_id"],
                "project_name": r["project_name"],
                "total_runs": r["total_runs"],
                "total_tests": tot,
                "passed_tests": passed,
                "failed_tests": int(r["failed_tests"]),
                "pass_percentage": rate,
            })

        return {"projects": items}
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 4. Bug Summary
# ===========================================================================

@router.get("/bug-summary")
def get_bug_summary(
    project_id: Optional[int] = Query(None, description="Optional project filter"),
    days: Optional[int] = Query(None, description="Filter to last N days"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Return bug reports grouped by severity and resolution status.
    Only includes bugs linked to test runs owned by current_user.
    """
    user_id = current_user["id"]
    start_d, end_d = _resolve_date_range(days=days, start_date=start_date, end_date=end_date)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if project_id is not None:
            _verify_project_ownership(project_id, user_id, cursor)

        # 1. Severity breakdown query
        sev_query = """
            SELECT
                LOWER(COALESCE(b.severity, 'low')) AS severity_key,
                COALESCE(b.severity, 'Low') AS severity_label,
                COUNT(b.id) AS bug_count
            FROM bug_reports b
            INNER JOIN test_runs tr ON b.run_id = tr.id
            WHERE tr.user_id = %s
        """
        sev_params: List[Any] = [user_id]

        if project_id is not None:
            sev_query += " AND tr.project_id = %s"
            sev_params.append(project_id)
        if start_d is not None:
            sev_query += " AND tr.started_at >= %s"
            sev_params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            sev_query += " AND tr.started_at <= %s"
            sev_params.append(datetime.combine(end_d, datetime.max.time()))

        sev_query += " GROUP BY LOWER(COALESCE(b.severity, 'low')), COALESCE(b.severity, 'Low')"
        cursor.execute(sev_query, tuple(sev_params))
        sev_rows = cursor.fetchall()

        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        severity_breakdown = []
        total_bugs = 0

        for r in sev_rows:
            key = r["severity_key"]
            count = r["bug_count"]
            total_bugs += count
            if key in by_severity:
                by_severity[key] += count
            else:
                by_severity[key] = count
            severity_breakdown.append({
                "severity": r["severity_label"],
                "count": count
            })

        # Ensure standard keys are present in severity_breakdown
        standard_labels = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
        present_keys = {r["severity_key"] for r in sev_rows}
        for k, label in standard_labels.items():
            if k not in present_keys:
                severity_breakdown.append({"severity": label, "count": 0})

        # Sort severity_breakdown by standard order
        order_map = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        severity_breakdown.sort(key=lambda x: order_map.get(x["severity"], 99))

        # 2. Status breakdown query
        status_query = """
            SELECT
                LOWER(COALESCE(b.status, 'open')) AS status_key,
                COALESCE(b.status, 'Open') AS status_label,
                COUNT(b.id) AS bug_count
            FROM bug_reports b
            INNER JOIN test_runs tr ON b.run_id = tr.id
            WHERE tr.user_id = %s
        """
        status_params: List[Any] = [user_id]

        if project_id is not None:
            status_query += " AND tr.project_id = %s"
            status_params.append(project_id)
        if start_d is not None:
            status_query += " AND tr.started_at >= %s"
            status_params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            status_query += " AND tr.started_at <= %s"
            status_params.append(datetime.combine(end_d, datetime.max.time()))

        status_query += " GROUP BY LOWER(COALESCE(b.status, 'open')), COALESCE(b.status, 'Open')"
        cursor.execute(status_query, tuple(status_params))
        status_rows = cursor.fetchall()

        by_status = {"open": 0, "resolved": 0, "closed": 0}
        status_breakdown = []

        for r in status_rows:
            s_key = r["status_key"]
            s_count = r["bug_count"]
            if s_key in by_status:
                by_status[s_key] += s_count
            else:
                by_status[s_key] = s_count
            status_breakdown.append({
                "status": r["status_label"],
                "count": s_count
            })

        for s_key in ("open", "resolved", "closed"):
            if not any(item["status"].lower() == s_key for item in status_breakdown):
                status_breakdown.append({"status": s_key.capitalize(), "count": 0})

        return {
            "total_bugs": total_bugs,
            "by_severity": by_severity,
            "by_status": by_status,
            "severity_breakdown": severity_breakdown,
            "status_breakdown": status_breakdown
        }
    finally:
        cursor.close()
        conn.close()


# ===========================================================================
# 5. Recent Activity
# ===========================================================================

@router.get("/recent-activity")
def get_recent_activity(
    project_id: Optional[int] = Query(None, description="Optional project filter"),
    days: Optional[int] = Query(None, description="Filter to last N days"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(10, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Return paginated recent test execution runs for the authenticated user.
    """
    user_id = current_user["id"]
    start_d, end_d = _resolve_date_range(days=days, start_date=start_date, end_date=end_date)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if project_id is not None:
            _verify_project_ownership(project_id, user_id, cursor)

        where_clauses = ["tr.user_id = %s"]
        params: List[Any] = [user_id]

        if project_id is not None:
            where_clauses.append("tr.project_id = %s")
            params.append(project_id)
        if start_d is not None:
            where_clauses.append("tr.started_at >= %s")
            params.append(datetime.combine(start_d, datetime.min.time()))
        if end_d is not None:
            where_clauses.append("tr.started_at <= %s")
            params.append(datetime.combine(end_d, datetime.max.time()))

        where_sql = " AND ".join(where_clauses)

        # Count total matching runs
        count_query = f"SELECT COUNT(*) AS total FROM test_runs tr WHERE {where_sql}"
        cursor.execute(count_query, tuple(params))
        total_count = cursor.fetchone()["total"]

        # Fetch page items
        query = f"""
            SELECT
                tr.id AS run_id,
                tr.project_id,
                COALESCE(p.project_name, 'Standalone API') AS project_name,
                tr.started_at AS created_at,
                tr.total_tests,
                tr.passed_tests,
                tr.failed_tests,
                CASE
                    WHEN tr.failed_tests = 0 AND tr.total_tests > 0 THEN 'PASS'
                    WHEN tr.failed_tests > 0 THEN 'FAIL'
                    ELSE 'EMPTY'
                END AS status,
                CASE
                    WHEN tr.total_tests > 0 THEN ROUND((tr.passed_tests / tr.total_tests) * 100, 1)
                    ELSE 0.0
                END AS pass_rate
            FROM test_runs tr
            LEFT JOIN projects p ON tr.project_id = p.id
            WHERE {where_sql}
            ORDER BY tr.id DESC
            LIMIT %s OFFSET %s
        """
        fetch_params = list(params) + [limit, offset]
        cursor.execute(query, tuple(fetch_params))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            created_str = r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
            items.append({
                "run_id": r["run_id"],
                "project_id": r["project_id"],
                "project_name": r["project_name"],
                "created_at": created_str,
                "total_tests": r["total_tests"],
                "passed_tests": r["passed_tests"],
                "failed_tests": r["failed_tests"],
                "status": r["status"],
                "pass_rate": float(r["pass_rate"]) if r["pass_rate"] is not None else 0.0,
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
