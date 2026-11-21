"""
Unit and integration tests for Usage Management, Atomic Quota Reservations,
Accurate AI Usage Logging, and Plan Feature Gating (Task 7.2).
"""

import pytest
from datetime import datetime, timezone, date
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

from agent_backend.app import app
from agent_backend import usage_service, plans, db_operations
from agent_backend.auth import create_access_token

client = TestClient(app)


def get_token(user_id: int, role: str = "user", plan: str = "free"):
    return create_access_token({"sub": str(user_id), "email": f"user{user_id}@example.com", "role": role})


class TestUsageMetricsCalculation:
    """Test that usage metrics calculate correctly from DB queries."""

    @patch("agent_backend.usage_service.get_db_connection")
    def test_get_user_usage_metrics(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"total": 4},
            {
                "total_runs": 15,
                "total_cases": 85,
                "passed_cases": 80,
                "failed_cases": 5,
                "last_activity": datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
            },
            {
                "monthly_runs": 7,
                "monthly_cases": 35
            },
            {
                "monthly_ai": 3
            },
        ]

        metrics = usage_service.get_user_usage_metrics(user_id=1)
        assert metrics["total_projects"] == 4
        assert metrics["total_test_runs"] == 15
        assert metrics["total_test_cases"] == 85
        assert metrics["total_passed_tests"] == 80
        assert metrics["total_failed_tests"] == 5
        assert metrics["monthly_test_runs"] == 7
        assert metrics["monthly_test_cases"] == 35
        assert metrics["monthly_ai_operations"] == 3
        assert "2026-11-18" in metrics["last_activity"]

    def test_get_current_month_start_utc(self):
        start = usage_service.get_current_month_start()
        now_utc = datetime.now(timezone.utc)
        assert start.tzinfo == timezone.utc
        assert start.year == now_utc.year
        assert start.month == now_utc.month
        assert start.day == 1
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0


class TestPlanDefinitionsAndPlatformModes:
    """Test plan matrices, unlimited quotas, and operational modes."""

    def test_plan_matrix_keys(self):
        assert "internal_demo" in plans.PLAN_DEFINITIONS
        assert "free" in plans.PLAN_DEFINITIONS
        assert "pro" in plans.PLAN_DEFINITIONS
        assert "business" in plans.PLAN_DEFINITIONS

    def test_internal_demo_is_unlimited_mode(self):
        demo_limits = plans.get_plan_config("internal_demo")
        assert demo_limits["max_projects"] == 100
        assert demo_limits["monthly_test_runs"] == 10000
        assert "ai_generation" in demo_limits["features"]
        assert "ai_analysis" in demo_limits["features"]

    def test_free_plan_excludes_ai_features(self):
        free_cfg = plans.get_plan_config("free")
        assert "ai_generation" not in free_cfg["features"]
        assert "ai_analysis" not in free_cfg["features"]
        assert "rule_based_testing" in free_cfg["features"]

    def test_unknown_plan_falls_back_to_internal_demo(self):
        limits = plans.get_plan_config("non_existent_plan")
        assert limits == plans.PLAN_DEFINITIONS["internal_demo"]

    def test_public_mode_defaults_registration_to_free(self, monkeypatch):
        monkeypatch.setenv("PLATFORM_MODE", "public")
        monkeypatch.delenv("DEFAULT_PLAN", raising=False)
        assert plans.get_default_registration_plan() == "free"

    def test_internal_mode_defaults_registration_to_internal_demo(self, monkeypatch):
        monkeypatch.setenv("PLATFORM_MODE", "internal")
        monkeypatch.delenv("DEFAULT_PLAN", raising=False)
        assert plans.get_default_registration_plan() == "internal_demo"


class TestAtomicQuotaReservation:
    """Test atomic test-run reservations and TOCTOU prevention."""

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_test_run_success(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock: user exists, monthly runs under quota, test cases under quota, ai ops under quota
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "pro"},   # user row locked
            {"total_runs": 10},         # active/completed runs
            {"total_cases": 100},       # monthly cases
            {"total_ai": 5},            # monthly ai ops
        ]
        mock_cursor.lastrowid = 1234

        run_id = usage_service.reserve_test_run(user_id=1, project_id=10, user_plan="pro")
        assert run_id == 1234
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_test_run_blocks_when_full(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "free"},   # user row locked
            {"total_runs": 50},          # Free plan allows 50 monthly runs
        ]

        with pytest.raises(HTTPException) as exc_info:
            usage_service.reserve_test_run(user_id=1, project_id=10, user_plan="free")
        assert exc_info.value.status_code == 429
        assert "Monthly test run limit reached" in exc_info.value.detail
        mock_conn.rollback.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reservation_cleanup_on_failure(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        usage_service.fail_test_run(run_id=999)
        assert mock_cursor.execute.called
        assert "UPDATE test_runs" in mock_cursor.execute.call_args[0][0]
        assert "SET status = 'failed'" in mock_cursor.execute.call_args[0][0]
        assert mock_cursor.execute.call_args[0][1] == (999,)
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reservation_completion(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        usage_service.complete_test_run(run_id=999, total_tests=10, passed_tests=9, failed_tests=1)
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_test_cases_quota_enforcement(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Free tier allows 500 test cases
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "free"},   # user row locked
            {"total_runs": 5},           # runs within 50
            {"total_cases": 500},        # test cases reached 500!
        ]

        with pytest.raises(HTTPException) as exc_info:
            usage_service.reserve_test_run(user_id=1, project_id=10, user_plan="free")
        assert exc_info.value.status_code == 429
        assert "Monthly test case limit reached" in exc_info.value.detail

    @patch("agent_backend.usage_service.get_db_connection")
    def test_unlimited_quota_never_blocked(self, mock_get_conn, monkeypatch):
        """Custom plan with -1 limits should never be blocked even if high count."""
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        custom_plan = {
            "name": "Custom",
            "max_projects": -1,
            "monthly_test_runs": -1,
            "monthly_test_cases": -1,
            "monthly_ai_operations": -1,
            "features": []
        }
        with patch("agent_backend.usage_service.get_plan_config", return_value=custom_plan):
            mock_cursor.fetchone.return_value = {"id": 1, "plan": "custom"}
            mock_cursor.lastrowid = 77
            run_id = usage_service.reserve_test_run(user_id=1, user_plan="custom")
            assert run_id == 77


class TestAccurateAIUsageLogging:
    """Test AI LLM call logging into ai_usage_logs."""

    @patch("agent_backend.db_operations.get_db_connection")
    def test_log_ai_usage_success(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.lastrowid = 101

        log_id = db_operations.log_ai_usage(
            user_id=1,
            run_id=5,
            call_type="generation",
            provider="gemini",
            model="gemini-flash-lite-latest",
            input_tokens=150,
            output_tokens=300,
            total_tokens=450,
            status="success"
        )
        assert log_id == 101
        assert mock_cursor.execute.called
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.db_operations.get_db_connection")
    def test_log_ai_usage_failure(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.lastrowid = 102

        log_id = db_operations.log_ai_usage(
            user_id=1,
            run_id=5,
            call_type="analysis",
            provider="gemini",
            model="gemini-flash-lite-latest",
            status="failed"
        )
        assert log_id == 102
        assert mock_cursor.execute.called


class TestFeatureGatingExecution:
    """Test feature gating in test execution."""

    @patch("agent_backend.engine.test_generator.test_executor.save_bug_report")
    @patch("agent_backend.engine.test_generator.test_executor.execute_test")
    @patch("agent_backend.engine.test_generator.test_executor.generate_ai_tests")
    @patch("agent_backend.engine.test_generator.test_executor.analyze_failure")
    @patch("agent_backend.engine.test_generator.test_executor.save_test_result")
    @patch("agent_backend.engine.test_generator.test_executor.update_test_run")
    @patch("agent_backend.engine.test_generator.test_executor.extract_endpoints")
    @patch("agent_backend.engine.test_generator.test_executor.load_openapi")
    @patch("agent_backend.engine.test_generator.test_executor.generate_all_tests")
    def test_free_plan_skips_ai_generation_and_analysis(
        self,
        mock_gen_rules,
        mock_load_spec,
        mock_extract_eps,
        mock_update_run,
        mock_save_result,
        mock_analyze_failure,
        mock_gen_ai,
        mock_execute_test,
        mock_save_bug,
    ):
        from agent_backend.engine.test_generator.test_executor import run_all_tests

        mock_load_spec.return_value = {}
        mock_extract_eps.return_value = [{"path": "/users", "method": "POST", "request_body": {"type": "object"}}]
        mock_gen_rules.return_value = [{
            "test_id": "TC-001",
            "method": "POST",
            "endpoint": "/users",
            "category": "Rule-Based",
            "expected_status": 201,
            "request": {"body": None, "headers": {}},
        }]
        mock_execute_test.return_value = {
            "test_id": "TC-001",
            "method": "POST",
            "endpoint": "/users",
            "category": "Rule-Based",
            "expected_status": 201,
            "expected": {"status_code": 201, "response_schema": None},
            "actual_status": 500,
            "actual": {"status_code": 500, "body": {"error": "Internal Error"}},
            "actual_body": {"error": "Internal Error"},
            "failure_reason": "Server returned 500",
            "failure_type": "API_DEFECT",
            "status": "FAIL",
            "headers": {},
            "body": {}
        }

        result = run_all_tests(
            base_url="http://127.0.0.1:8000",
            user_id=1,
            enable_ai_generation=False,
            enable_ai_analysis=False,
            run_id=10
        )

        # AI generation and Gemini failure analysis must NOT have been called
        assert not mock_gen_ai.called
        assert not mock_analyze_failure.called

        # Rule-based testing still succeeded
        assert result["total"] == 1
        assert result["failed"] == 1
        assert result["results"][0]["bug_report"] is not None
        assert result["results"][0]["ai_analysis"]["is_ai"] is False


class TestAPIEndpointUsageIntegration:
    """Test HTTP API endpoints honoring usage checks."""

    @patch("agent_backend.routes.projects.check_project_limit")
    @patch("agent_backend.db_operations.get_user_by_id")
    def test_post_projects_respects_usage_check_rejection(self, mock_get_user, mock_check_limit):
        mock_get_user.return_value = {
            "id": 1,
            "full_name": "Test User",
            "email": "user@example.com",
            "role": "user",
            "plan": "free"
        }
        mock_check_limit.side_effect = HTTPException(status_code=429, detail="Project limit reached (3/3)")

        token = get_token(1)
        resp = client.post(
            "/projects",
            json={"project_name": "Overflow Project", "base_url": "http://127.0.0.1:8000"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 429
        assert "Project limit reached" in resp.json()["detail"]

    @patch("agent_backend.app.check_test_run_limit")
    @patch("agent_backend.db_operations.get_user_by_id")
    def test_post_run_tests_respects_usage_check_rejection(self, mock_get_user, mock_check_limit):
        mock_get_user.return_value = {
            "id": 1,
            "full_name": "Test User",
            "email": "user@example.com",
            "role": "user",
            "plan": "free"
        }
        mock_check_limit.side_effect = HTTPException(status_code=429, detail="Monthly test run limit reached")

        token = get_token(1)
        resp = client.post(
            "/run-tests",
            json={"base_url": "http://127.0.0.1:8000"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 429
        assert "Monthly test run limit reached" in resp.json()["detail"]


# ===========================================================================
# 8. Heartbeat & Stale Reservation Recovery (Task 7.4 Fix 3)
# ===========================================================================

class TestHeartbeatAndStaleRecovery:
    """Test heartbeat updates and recovery of abandoned runs."""

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reconcile_stale_reservations(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 3

        reconciled = usage_service.reconcile_stale_reservations(timeout_minutes=5)
        assert reconciled == 3
        assert mock_cursor.execute.called
        assert "UPDATE test_runs" in mock_cursor.execute.call_args[0][0]
        assert "SET status = 'failed'" in mock_cursor.execute.call_args[0][0]
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_update_heartbeat(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 1

        ok = usage_service.update_heartbeat(run_id=42)
        assert ok is True
        assert "heartbeat_at = UTC_TIMESTAMP()" in mock_cursor.execute.call_args[0][0]
        mock_conn.commit.assert_called_once()


# ===========================================================================
# 9. Idempotency Key Handling (Task 7.4 Fix 4)
# ===========================================================================

class TestIdempotencyLogic:
    """Test Idempotency-Key support on POST /run-tests."""

    @patch("agent_backend.usage_service.get_db_connection")
    def test_get_idempotent_test_run(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "id": 105,
            "status": "completed",
            "total_tests": 12,
            "passed_tests": 12,
            "failed_tests": 0,
            "started_at": datetime(2026, 11, 19, 10, 0, 0)
        }

        run = usage_service.get_idempotent_test_run(user_id=1, idempotency_key="unique-key-123")
        assert run is not None
        assert run["id"] == 105
        assert run["status"] == "completed"

    @patch("agent_backend.app.get_idempotent_test_run")
    @patch("agent_backend.app.get_db_connection")
    @patch("agent_backend.db_operations.get_user_by_id")
    def test_post_run_tests_returns_cached_completed_results(self, mock_get_user, mock_get_conn, mock_get_idemp):
        mock_get_user.return_value = {
            "id": 1,
            "full_name": "Test User",
            "email": "user@example.com",
            "role": "user",
            "plan": "free"
        }
        mock_get_idemp.return_value = {
            "id": 200,
            "status": "completed",
            "total_tests": 5,
            "passed_tests": 5,
            "failed_tests": 0
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "run_id": 200, "test_id": "TC-01", "status": "PASS"}
        ]

        token = get_token(1)
        resp = client.post(
            "/run-tests",
            json={"base_url": "http://127.0.0.1:8000"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "my-replay-key"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body.get("idempotent_replay") is True
        assert body["data"]["run_id"] == 200
        assert body["data"]["total"] == 5


# ===========================================================================
# 10. Advanced Test Case & AI Quota Reservations (Task 7.4 Fix 1 & Fix 2)
# ===========================================================================

class TestAdvancedReservations:
    """Test test-case quota pre-allocation and individual AI operation reservations."""

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_test_case_quota_success(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "free"},
            {"completed_cases": 100},
            {"in_flight_cases": 50},
        ]

        budget = usage_service.reserve_test_case_quota(
            user_id=1,
            run_id=10,
            estimated_tests=50,
            user_plan="free"
        )
        assert budget == 350
        mock_conn.commit.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_test_case_quota_exceeded_blocks_before_execution(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "free"},
            {"completed_cases": 450},
            {"in_flight_cases": 30},
        ]

        with pytest.raises(HTTPException) as exc_info:
            usage_service.reserve_test_case_quota(
                user_id=1,
                run_id=10,
                estimated_tests=50,
                user_plan="free"
            )
        assert exc_info.value.status_code == 429
        assert "Monthly test case limit exceeded" in exc_info.value.detail
        mock_conn.rollback.assert_called_once()

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_ai_operation_lifecycle(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Test successful reservation under quota
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "pro"},
            {"total_ai": 200},
        ]
        mock_cursor.lastrowid = 888

        log_id = usage_service.reserve_ai_operation(
            user_id=1,
            run_id=10,
            call_type="generation",
            user_plan="pro"
        )
        assert log_id == 888

        # Test completion
        usage_service.complete_ai_operation(log_id=888, input_tokens=100, output_tokens=200, total_tokens=300)
        assert "UPDATE ai_usage_logs" in mock_cursor.execute.call_args[0][0]
        assert "status = 'success'" in mock_cursor.execute.call_args[0][0]

        # Test failure
        usage_service.fail_ai_operation(log_id=888)
        assert "status = 'failed'" in mock_cursor.execute.call_args[0][0]

    @patch("agent_backend.usage_service.get_db_connection")
    def test_reserve_ai_operation_exhausted_returns_none(self, mock_get_conn, monkeypatch):
        monkeypatch.setenv("ENFORCE_USAGE_LIMITS", "true")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Pro plan allows 500
        mock_cursor.fetchone.side_effect = [
            {"id": 1, "plan": "pro"},
            {"total_ai": 500},
        ]

        log_id = usage_service.reserve_ai_operation(
            user_id=1,
            run_id=10,
            call_type="analysis",
            user_plan="pro"
        )
        assert log_id is None
        mock_conn.rollback.assert_called_once()
