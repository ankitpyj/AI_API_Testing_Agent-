"""
Unit tests for Gemini API retry architecture (gemini_retry.py) and integration
with ai_failure_analyzer.py and ai_test_generator.py.

All tests use mocks — zero real external API calls.
"""

import sys
import os
from unittest.mock import MagicMock, patch, call
import pytest

# Path setup
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_ROOT = os.path.join(REPO_ROOT, "agent_backend")
ENGINE_ROOT = os.path.join(BACKEND_ROOT, "engine")

for p in [ENGINE_ROOT, BACKEND_ROOT, REPO_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Stub mysql / database if not present
if "mysql" not in sys.modules:
    _mock_mysql = MagicMock()
    sys.modules["mysql"] = _mock_mysql
    sys.modules["mysql.connector"] = _mock_mysql.connector

if "database" not in sys.modules:
    sys.modules["database"] = MagicMock()

if "db_operations" not in sys.modules:
    sys.modules["db_operations"] = MagicMock()

from engine.common.gemini_retry import (
    is_transient_error,
    extract_retry_after,
    execute_with_retry,
)


class MockAPIStatusError(Exception):
    """Mock exception resembling openai.APIStatusError."""
    def __init__(self, message, status_code, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = MagicMock()
        self.response.headers = headers or {}


# ===========================================================================
# 1. Error Classification (Transient vs Permanent)
# ===========================================================================

class TestErrorClassification:

    def test_503_is_transient(self):
        exc = MockAPIStatusError("Service Unavailable", 503)
        assert is_transient_error(exc) is True

    def test_503_high_demand_message_is_transient(self):
        exc = RuntimeError("This model is currently experiencing high demand. Spikes in demand are usually temporary.")
        assert is_transient_error(exc) is True

    def test_429_rate_limit_is_transient(self):
        exc = MockAPIStatusError("Too Many Requests", 429)
        assert is_transient_error(exc) is True

    def test_resource_exhausted_message_is_transient(self):
        exc = Exception("RESOURCE_EXHAUSTED: You exceeded your current quota.")
        assert is_transient_error(exc) is True

    def test_timeout_error_is_transient(self):
        assert is_transient_error(TimeoutError("Read timed out")) is True

    def test_connection_error_is_transient(self):
        assert is_transient_error(ConnectionError("Connection refused")) is True

    def test_400_bad_request_is_permanent(self):
        exc = MockAPIStatusError("Bad Request", 400)
        assert is_transient_error(exc) is False

    def test_401_unauthorized_is_permanent(self):
        exc = MockAPIStatusError("Invalid API Key", 401)
        assert is_transient_error(exc) is False

    def test_403_forbidden_is_permanent(self):
        exc = MockAPIStatusError("Permission Denied", 403)
        assert is_transient_error(exc) is False

    def test_404_not_found_is_permanent(self):
        exc = MockAPIStatusError("Model Not Found", 404)
        assert is_transient_error(exc) is False

    def test_422_unprocessable_is_permanent(self):
        exc = MockAPIStatusError("Unprocessable Entity", 422)
        assert is_transient_error(exc) is False


# ===========================================================================
# 2. Retry-After Header Extraction
# ===========================================================================

class TestRetryAfterExtraction:

    def test_extract_seconds_integer(self):
        exc = MockAPIStatusError("Rate limited", 429, headers={"retry-after": "5"})
        assert extract_retry_after(exc) == 5.0

    def test_extract_seconds_float(self):
        exc = MockAPIStatusError("Rate limited", 429, headers={"Retry-After": "2.5"})
        assert extract_retry_after(exc) == 2.5

    def test_extract_missing_header_returns_none(self):
        exc = MockAPIStatusError("Rate limited", 429, headers={})
        assert extract_retry_after(exc) is None

    def test_extract_non_http_exception_returns_none(self):
        assert extract_retry_after(RuntimeError("error")) is None


# ===========================================================================
# 3. Retry Execution Logic and Backoff Schedule
# ===========================================================================

class TestExecuteWithRetry:

    @patch("time.sleep", return_value=None)
    def test_succeeds_on_first_try_no_retries(self, mock_sleep):
        fn = MagicMock(return_value="success")
        result = execute_with_retry(fn, max_retries=3)
        assert result == "success"
        assert fn.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    def test_retries_transient_503_and_succeeds_on_second_try(self, mock_sleep):
        fn = MagicMock(side_effect=[MockAPIStatusError("Spike", 503), "recovered"])
        result = execute_with_retry(fn, max_retries=3, base_delay=2.0, jitter_range=(0.0, 0.0))
        assert result == "recovered"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(2.0)

    @patch("time.sleep", return_value=None)
    def test_retries_transient_429_and_succeeds_on_third_try(self, mock_sleep):
        fn = MagicMock(side_effect=[
            MockAPIStatusError("Rate limited", 429),
            MockAPIStatusError("High demand", 503),
            "final_success"
        ])
        result = execute_with_retry(fn, max_retries=3, base_delay=2.0, jitter_range=(0.0, 0.0))
        assert result == "final_success"
        assert fn.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(2.0), call(4.0)])

    @patch("time.sleep", return_value=None)
    def test_exhausted_retries_raises_original_exception(self, mock_sleep):
        err = MockAPIStatusError("Persistent 503", 503)
        fn = MagicMock(side_effect=err)
        with pytest.raises(MockAPIStatusError) as exc_info:
            execute_with_retry(fn, max_retries=3, base_delay=2.0, jitter_range=(0.0, 0.0))
        assert exc_info.value is err
        assert fn.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("time.sleep", return_value=None)
    def test_permanent_error_fails_fast_zero_retries(self, mock_sleep):
        err = MockAPIStatusError("Unauthorized key", 401)
        fn = MagicMock(side_effect=err)
        with pytest.raises(MockAPIStatusError):
            execute_with_retry(fn, max_retries=3)
        assert fn.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    def test_respects_retry_after_header_when_larger_than_step(self, mock_sleep):
        err = MockAPIStatusError("Rate limited", 429, headers={"retry-after": "7.0"})
        fn = MagicMock(side_effect=[err, "ok"])
        res = execute_with_retry(fn, max_retries=3, base_delay=2.0, jitter_range=(0.0, 0.0))
        assert res == "ok"
        mock_sleep.assert_called_once_with(7.0)


# ===========================================================================
# 4. AI Analyzer Integration with Retry & Fallback
# ===========================================================================

class TestAIAnalyzerRetryIntegration:

    @patch("time.sleep", return_value=None)
    def test_analyzer_retries_on_503_and_returns_analysis(self, mock_sleep):
        import engine.ai_analyzer.ai_failure_analyzer as mod

        fake_resp = MagicMock()
        fake_resp.choices = [
            MagicMock(message=MagicMock(content='{"summary": "Fixed", "possible_cause": "Bug", "severity": "High", "recommendation": "Patch it"}'))
        ]

        # Fail once with 503, then succeed
        mock_create = MagicMock(side_effect=[
            MockAPIStatusError("Demand spike", 503),
            fake_resp
        ])

        with patch.object(mod.client.chat.completions, "create", mock_create):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result.get("analyzer_failed") is not True
        assert result["summary"] == "Fixed"
        assert mock_create.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep", return_value=None)
    def test_analyzer_safe_fallback_when_retries_exhausted(self, mock_sleep):
        import engine.ai_analyzer.ai_failure_analyzer as mod

        mock_create = MagicMock(side_effect=MockAPIStatusError("Unavailable", 503))

        with patch.object(mod.client.chat.completions, "create", mock_create):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result["analyzer_failed"] is True
        assert "unavailable" in result["possible_cause"].lower()
        assert mock_create.call_count == 3  # retried up to max

    @patch("time.sleep", return_value=None)
    def test_analyzer_fails_fast_on_404_no_wasted_retries(self, mock_sleep):
        import engine.ai_analyzer.ai_failure_analyzer as mod

        mock_create = MagicMock(side_effect=MockAPIStatusError("Model Not Found", 404))

        with patch.object(mod.client.chat.completions, "create", mock_create):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result["analyzer_failed"] is True
        assert mock_create.call_count == 1  # No retries on 404
        mock_sleep.assert_not_called()


# ===========================================================================
# 5. AI Test Generator Integration with Retry & Fallback
# ===========================================================================

class TestAITestGeneratorRetryIntegration:

    @patch("time.sleep", return_value=None)
    def test_generator_retries_on_429_and_succeeds(self, mock_sleep):
        import engine.ai_generator.ai_test_generator as gen
        import json

        payload = {
            "tests": [
                {
                    "category": "boundary",
                    "description": f"t{i}",
                    "request": {"body": {"name": "Test", "age": 20}},
                    "expected": {"status_code": 200},
                    "expected_source": "openapi_spec",
                    "expectation_confidence": "high",
                    "requires_review": False,
                    "review_reason": None,
                }
                for i in range(5)
            ]
        }

        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]

        mock_create = MagicMock(side_effect=[
            MockAPIStatusError("Quota reached", 429),
            fake_resp,
        ])

        with patch.object(gen.client.chat.completions, "create", mock_create):
            tests = gen.generate_ai_tests({
                "path": "/users",
                "method": "POST",
                "request_body": {"fields": []},
                "responses": [{"status_code": 200}],
            })

        assert len(tests) == 5
        assert mock_create.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep", return_value=None)
    def test_generator_fails_fast_on_401_returns_empty_list(self, mock_sleep):
        import engine.ai_generator.ai_test_generator as gen

        mock_create = MagicMock(side_effect=MockAPIStatusError("Invalid API Key", 401))

        with patch.object(gen.client.chat.completions, "create", mock_create):
            tests = gen.generate_ai_tests({
                "path": "/users",
                "method": "POST",
                "request_body": {"fields": []},
                "responses": [{"status_code": 200}],
            })

        assert tests == []
        assert mock_create.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    def test_generator_safe_empty_list_on_retries_exhausted(self, mock_sleep):
        import engine.ai_generator.ai_test_generator as gen

        mock_create = MagicMock(side_effect=MockAPIStatusError("Persistent 503", 503))

        with patch.object(gen.client.chat.completions, "create", mock_create):
            tests = gen.generate_ai_tests({
                "path": "/users",
                "method": "POST",
                "request_body": {"fields": []},
                "responses": [{"status_code": 200}],
            })

        assert tests == []
        assert mock_create.call_count == 3

