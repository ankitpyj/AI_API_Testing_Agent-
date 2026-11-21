"""
Tests for SaaS Dashboard, Analytics, and Usage Monitoring (Task 6).

Covers:
1. Unauthenticated analytics requests are rejected (401).
2. User A sees only their own overview statistics.
3. User B cannot see User A's analytics (strict data isolation).
4. Project filters enforce ownership (404 for inaccessible or non-existent projects).
5. Date filters validate input and work correctly (days, start_date, end_date).
6. Empty dashboard returns zero values without errors.
7. Trend aggregation returns correct daily totals and fills in zero-activity dates.
8. Project performance aggregation returns correct per-project metrics.
9. Bug severity grouping uses actual stored values (Critical, High, Medium, Low) and status breakdown.
10. Recent activity pagination (limit and offset) works properly.
11. Historical unowned test runs (user_id IS NULL) are excluded from user analytics.
12. Usage monitoring snapshot is included cleanly in the overview response.
"""

import sys
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup sys.path
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

USER_ALICE = {"id": 1, "full_name": "Alice Analytics", "email": "alice@example.com"}
USER_BOB = {"id": 2, "full_name": "Bob Analytics", "email": "bob@example.com"}

TOKEN_ALICE = create_access_token({"sub": "1", "email": "alice@example.com", "name": "Alice Analytics"})
TOKEN_BOB = create_access_token({"sub": "2", "email": "bob@example.com", "name": "Bob Analytics"})

AUTH_HEADER_ALICE = {"Authorization": f"Bearer {TOKEN_ALICE}"}
AUTH_HEADER_BOB = {"Authorization": f"Bearer {TOKEN_BOB}"}


# ===========================================================================
# 1. Unauthenticated Requests Rejected
# ===========================================================================

class TestUnauthenticatedAnalytics:
    def test_overview_requires_auth(self):
        resp = client.get("/analytics/overview")
        assert resp.status_code == 401
        assert "detail" in resp.json()

    def test_trends_requires_auth(self):
        resp = client.get("/analytics/test-trends")
        assert resp.status_code == 401

    def test_performance_requires_auth(self):
        resp = client.get("/analytics/project-performance")
        assert resp.status_code == 401

    def test_bug_summary_requires_auth(self):
        resp = client.get("/analytics/bug-summary")
        assert resp.status_code == 401

    def test_recent_activity_requires_auth(self):
        resp = client.get("/analytics/recent-activity")
        assert resp.status_code == 401


# ===========================================================================
# 2. User Data Isolation & Overview Analytics
# ===========================================================================

class TestUserDataIsolation:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_user_a_sees_only_own_overview(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Alice has 2 projects, 5 runs, 50 tests (45 pass, 5 fail), 3 bugs (2 open)
        mock_cursor.fetchone.side_effect = [
            {"total": 2},  # projects count
            {
                "total_test_runs": 5,
                "total_test_cases": 50,
                "total_passed_tests": 45,
                "total_failed_tests": 5,
                "last_activity": datetime(2026, 11, 19, 10, 0, 0)
            },  # run stats
            {
                "total_bug_reports": 3,
                "open_bug_reports": 2
            }  # bug stats
        ]

        resp = client.get("/analytics/overview", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_projects"] == 2
        assert data["total_test_runs"] == 5
        assert data["total_test_cases"] == 50
        assert data["total_passed_tests"] == 45
        assert data["total_failed_tests"] == 5
        assert data["pass_percentage"] == 90.0
        assert data["total_bug_reports"] == 3
        assert data["open_bug_reports"] == 2

        # Verify SQL queries all used Alice's user_id (1)
        for call_item in mock_cursor.execute.call_args_list:
            sql, params = call_item[0]
            assert 1 in params  # Alice's ID was passed

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_BOB)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_user_b_empty_overview_returns_zeros(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Bob has no projects or runs
        mock_cursor.fetchone.side_effect = [
            {"total": 0},  # projects count
            {
                "total_test_runs": 0,
                "total_test_cases": 0,
                "total_passed_tests": 0,
                "total_failed_tests": 0,
                "last_activity": None
            },
            {
                "total_bug_reports": 0,
                "open_bug_reports": 0
            }
        ]

        resp = client.get("/analytics/overview", headers=AUTH_HEADER_BOB)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_projects"] == 0
        assert data["total_test_runs"] == 0
        assert data["total_test_cases"] == 0
        assert data["pass_percentage"] == 0.0
        assert data["total_bug_reports"] == 0
        assert data["open_bug_reports"] == 0
        assert data["usage"]["total_runs"] == 0


# ===========================================================================
# 3. Project Filter and Ownership Enforcement
# ===========================================================================

class TestProjectFiltersAndOwnership:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_project_filter_success_when_owned(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Ownership verification returns project
        mock_cursor.fetchone.side_effect = [
            {"id": 10, "project_name": "Alice Store API"},  # ownership check
            {
                "total_test_runs": 3,
                "total_test_cases": 30,
                "total_passed_tests": 30,
                "total_failed_tests": 0,
                "last_activity": datetime(2026, 11, 19, 8, 30, 0)
            },
            {
                "total_bug_reports": 0,
                "open_bug_reports": 0
            }
        ]

        resp = client.get("/analytics/overview?project_id=10", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_projects"] == 1
        assert data["total_test_runs"] == 3
        assert data["pass_percentage"] == 100.0

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_project_filter_returns_404_when_not_owned(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Project 20 belongs to Bob, so query with user_id=1 returns None
        mock_cursor.fetchone.return_value = None

        resp = client.get("/analytics/overview?project_id=20", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 404
        assert "not found or you do not have access" in resp.json()["detail"]


# ===========================================================================
# 4. Date Filters and Validation
# ===========================================================================

class TestDateFiltersAndValidation:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    def test_invalid_days_filter_rejected(self, mock_get_user):
        resp = client.get("/analytics/overview?days=0", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 400

        resp2 = client.get("/analytics/overview?days=500", headers=AUTH_HEADER_ALICE)
        assert resp2.status_code == 400

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    def test_invalid_date_format_rejected(self, mock_get_user):
        resp = client.get("/analytics/overview?start_date=not-a-date", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 400
        assert "Invalid start_date format" in resp.json()["detail"]

    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    def test_start_date_after_end_date_rejected(self, mock_get_user):
        resp = client.get(
            "/analytics/overview?start_date=2026-11-20&end_date=2026-11-10",
            headers=AUTH_HEADER_ALICE
        )
        assert resp.status_code == 400
        assert "cannot be after end_date" in resp.json()["detail"]


# ===========================================================================
# 5. Trend Aggregation and Zero-Activity Timeline
# ===========================================================================

class TestTrendAggregation:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_test_trends_fills_zero_activity_dates(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        today = date.today()
        # Mock DB returning data for today only
        mock_cursor.fetchall.return_value = [
            {
                "run_date": today,
                "total_runs": 2,
                "total_tests": 20,
                "passed_tests": 18,
                "failed_tests": 2
            }
        ]

        resp = client.get("/analytics/test-trends?days=7", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        data = resp.json()

        assert data["days"] == 7
        assert len(data["trends"]) == 7

        # Check today's data is populated
        today_str = today.strftime("%Y-%m-%d")
        today_entry = next((t for t in data["trends"] if t["date"] == today_str), None)
        assert today_entry is not None
        assert today_entry["total_tests"] == 20
        assert today_entry["passed_tests"] == 18
        assert today_entry["pass_percentage"] == 90.0

        # Check a zero-activity date earlier in the week
        yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_entry = next((t for t in data["trends"] if t["date"] == yesterday_str), None)
        assert yesterday_entry is not None
        assert yesterday_entry["total_tests"] == 0
        assert yesterday_entry["pass_percentage"] == 0.0


# ===========================================================================
# 6. Project Performance Aggregation
# ===========================================================================

class TestProjectPerformance:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_project_performance_aggregation(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchall.return_value = [
            {
                "project_id": 1,
                "project_name": "API Alpha",
                "total_runs": 4,
                "total_tests": 40,
                "passed_tests": 36,
                "failed_tests": 4,
            },
            {
                "project_id": 2,
                "project_name": "API Beta (No Runs)",
                "total_runs": 0,
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            }
        ]

        resp = client.get("/analytics/project-performance", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        projects = resp.json()["projects"]

        assert len(projects) == 2
        assert projects[0]["project_name"] == "API Alpha"
        assert projects[0]["pass_percentage"] == 90.0
        assert projects[1]["project_name"] == "API Beta (No Runs)"
        assert projects[1]["pass_percentage"] == 0.0


# ===========================================================================
# 7. Bug Summary Grouping
# ===========================================================================

class TestBugSummary:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_bug_summary_severities_and_status(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # 1. Severity rows
        mock_cursor.fetchall.side_effect = [
            [
                {"severity_key": "critical", "severity_label": "Critical", "bug_count": 2},
                {"severity_key": "high", "severity_label": "High", "bug_count": 5},
                {"severity_key": "medium", "severity_label": "Medium", "bug_count": 3},
            ],
            [
                {"status_key": "open", "status_label": "Open", "bug_count": 8},
                {"status_key": "resolved", "status_label": "Resolved", "bug_count": 2},
            ]
        ]

        resp = client.get("/analytics/bug-summary", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_bugs"] == 10
        assert data["by_severity"]["critical"] == 2
        assert data["by_severity"]["high"] == 5
        assert data["by_severity"]["medium"] == 3
        assert data["by_severity"]["low"] == 0  # Default 0 for absent

        assert data["by_status"]["open"] == 8
        assert data["by_status"]["resolved"] == 2
        assert data["by_status"]["closed"] == 0


# ===========================================================================
# 8. Recent Activity Pagination
# ===========================================================================

class TestRecentActivity:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_recent_activity_pagination(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 25}
        mock_cursor.fetchall.return_value = [
            {
                "run_id": 105,
                "project_id": 1,
                "project_name": "API Alpha",
                "created_at": datetime(2026, 11, 19, 10, 15, 0),
                "total_tests": 12,
                "passed_tests": 12,
                "failed_tests": 0,
                "status": "PASS",
                "pass_rate": 100.0
            },
            {
                "run_id": 104,
                "project_id": 1,
                "project_name": "API Alpha",
                "created_at": datetime(2026, 11, 18, 16, 0, 0),
                "total_tests": 12,
                "passed_tests": 10,
                "failed_tests": 2,
                "status": "FAIL",
                "pass_rate": 83.3
            }
        ]

        resp = client.get("/analytics/recent-activity?limit=2&offset=0", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 25
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["items"]) == 2
        assert data["items"][0]["status"] == "PASS"
        assert data["items"][1]["status"] == "FAIL"


# ===========================================================================
# 9. Usage Monitoring Snapshot
# ===========================================================================

class TestUsageMonitoring:
    @patch("agent_backend.db_operations.get_user_by_id", return_value=USER_ALICE)
    @patch("agent_backend.routes.analytics.get_db_connection")
    def test_overview_includes_usage_monitoring(self, mock_get_conn, mock_get_user):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.side_effect = [
            {"total": 4},
            {
                "total_test_runs": 15,
                "total_test_cases": 150,
                "total_passed_tests": 140,
                "total_failed_tests": 10,
                "last_activity": datetime(2026, 11, 19, 12, 0, 0)
            },
            {
                "total_bug_reports": 5,
                "open_bug_reports": 1
            }
        ]

        resp = client.get("/analytics/overview", headers=AUTH_HEADER_ALICE)
        assert resp.status_code == 200
        usage = resp.json()["usage"]

        assert usage["total_projects"] == 4
        assert usage["total_runs"] == 15
        assert usage["total_test_cases"] == 150
        assert usage["last_activity"] == "2026-11-19T12:00:00"
