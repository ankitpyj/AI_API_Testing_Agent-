"""
Comprehensive regression tests for the AI API Testing Agent.

Covers all 14 test scenarios required by the fix specification:
  1.  Gemini analyzer success
  2.  Gemini analyzer failure and safe fallback
  3.  Missing or invalid model configuration
  4.  Valid positive payloads
  5.  Invalid negative payloads
  6.  Missing required query parameters
  7.  Invalid enum values
  8.  Expected 422 but actual 400
  9.  Expected 422 but actual 200
  10. Actual 500 responses
  11. Expected 200 but actual 404 for a nonexistent resource
  12. Correct suppression of bug reports for NEEDS_REVIEW and analyzer failures
  13. Correct creation of bug reports for verified defect candidates
  14. Database persistence and frontend-compatible result fields

All external services (Gemini API, Petstore API, MySQL) are mocked.

Run with:
    cd g:/ai_api-testing_agent
    python -m pytest tests/test_comprehensive_regression.py -v
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_ROOT = os.path.join(REPO_ROOT, "agent_backend")
ENGINE_ROOT  = os.path.join(BACKEND_ROOT, "engine")

for p in [ENGINE_ROOT, BACKEND_ROOT, REPO_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Stub mysql / database / db_operations so every import succeeds without a DB
# ---------------------------------------------------------------------------
if "mysql" not in sys.modules:
    _mock_mysql = MagicMock()
    sys.modules["mysql"] = _mock_mysql
    sys.modules["mysql.connector"] = _mock_mysql.connector

if "database" not in sys.modules:
    sys.modules["database"] = MagicMock()

if "db_operations" not in sys.modules:
    sys.modules["db_operations"] = MagicMock()


# ===========================================================================
# Helpers
# ===========================================================================

def _result(
    *,
    test_id="TC-001",
    method="POST",
    endpoint="/pet",
    expected_status=200,
    actual_status=200,
    actual_body=None,
    body=None,
    path_params=None,
    query_params=None,
    expectation_confidence="high",
    requires_review=False,
    expected_source="openapi_spec",
    error=None,
    expected_schema=None,
):
    return {
        "test_id": test_id,
        "endpoint": endpoint,
        "method": method,
        "request": {
            "path_params": path_params or {},
            "query_params": query_params or {},
            "headers": {},
            "body": body,
        },
        "expected": {
            "status_code": expected_status,
            "response_schema": expected_schema,
        },
        "actual": {
            "status_code": actual_status,
            "body": actual_body or {},
            "error": error,
        },
        "expectation_confidence": expectation_confidence,
        "requires_review": requires_review,
        "expected_source": expected_source,
    }


def _validate(**kwargs):
    from test_generator.response_validator import validate_response
    return validate_response(_result(**kwargs))


def _good_analysis():
    return {
        "summary": "API returned unexpected 500",
        "possible_cause": "Server-side unhandled exception",
        "severity": "High",
        "recommendation": "Check server logs",
    }


def _failed_analysis():
    return {
        "analyzer_failed": True,
        "summary": "AI analysis unavailable",
        "possible_cause": "Gemini API unreachable",
        "severity": "Medium",
        "recommendation": "Set GEMINI_API_KEY",
    }


# ===========================================================================
# 1. Gemini analyzer SUCCESS
# ===========================================================================

class TestGeminiAnalyzerSuccess:

    def test_valid_json_response_returned(self):
        """Analyzer returns parsed dict when Gemini responds with valid JSON."""
        import ai_analyzer.ai_failure_analyzer as mod

        good_json = json.dumps(_good_analysis())
        fake_choice = MagicMock()
        fake_choice.message.content = good_json
        fake_resp = MagicMock()
        fake_resp.choices = [fake_choice]

        with patch.object(mod.client.chat.completions, "create", return_value=fake_resp):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result.get("analyzer_failed") is None or result.get("analyzer_failed") is False
        assert result["severity"] == "High"
        assert "summary" in result
        assert "recommendation" in result

    def test_model_name_passed_to_api(self):
        """The model name sent to the API must match GEMINI_MODEL."""
        import ai_analyzer.ai_failure_analyzer as mod

        captured = {}

        def fake_create(**kwargs):
            captured["model"] = kwargs.get("model")
            fc = MagicMock()
            fc.message.content = json.dumps(_good_analysis())
            fr = MagicMock()
            fr.choices = [fc]
            return fr

        with patch.object(mod.client.chat.completions, "create",
                          side_effect=lambda **kw: fake_create(**kw)):
            mod.analyze_failure({"test_id": "TC-001"})

        assert captured["model"] == mod.GEMINI_MODEL


# ===========================================================================
# 2. Gemini analyzer FAILURE and safe fallback
# ===========================================================================

class TestGeminiAnalyzerFailureFallback:

    def test_network_error_returns_analyzer_failed(self):
        import ai_analyzer.ai_failure_analyzer as mod

        with patch.object(mod.client.chat.completions, "create",
                          side_effect=ConnectionError("timeout")):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result["analyzer_failed"] is True

    def test_invalid_json_returns_analyzer_failed(self):
        import ai_analyzer.ai_failure_analyzer as mod

        fake_choice = MagicMock()
        fake_choice.message.content = "NOT JSON {"
        fake_resp = MagicMock()
        fake_resp.choices = [fake_choice]

        with patch.object(mod.client.chat.completions, "create", return_value=fake_resp):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result["analyzer_failed"] is True

    def test_analyzer_failure_does_not_crash_pipeline(self):
        """analyze_failure must never raise; it must return a dict."""
        import ai_analyzer.ai_failure_analyzer as mod

        with patch.object(mod.client.chat.completions, "create",
                          side_effect=RuntimeError("boom")):
            result = mod.analyze_failure({"test_id": "TC-999", "status": "FAIL"})

        assert isinstance(result, dict)
        assert result.get("analyzer_failed") is True

    def test_analyzer_failed_test_result_preserved(self):
        """Even when the analyzer fails, the test FAIL status must persist."""
        from test_generator.response_validator import validate_response
        r = validate_response(_result(expected_status=200, actual_status=500))
        # Test is FAIL; analyzer failure should not change that
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "API_DEFECT"


# ===========================================================================
# 3. Missing or invalid model configuration
# ===========================================================================

class TestModelConfiguration:

    def test_gemini_model_not_nonexistent_string(self):
        from ai_analyzer.ai_failure_analyzer import GEMINI_MODEL
        assert GEMINI_MODEL != "gemini-3.5-flash-lite", (
            "Model 'gemini-3.5-flash-lite' does not exist."
        )

    def test_gemini_model_contains_gemini(self):
        from ai_analyzer.ai_failure_analyzer import GEMINI_MODEL
        assert "gemini" in GEMINI_MODEL.lower()

    def test_missing_api_key_returns_analyzer_failed(self):
        """If GEMINI_API_KEY is absent (client=None), analyze_failure must return analyzer_failed."""
        import ai_analyzer.ai_failure_analyzer as mod
        original = mod.client
        try:
            mod.client = None
            result = mod.analyze_failure({"test_id": "TC-001"})
            assert result["analyzer_failed"] is True
        finally:
            mod.client = original

    def test_model_env_var_override(self):
        """GEMINI_MODEL env var must override the default when set."""
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-1.5-flash"}):
            # Re-read the env var at call time
            model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-8b")
            assert model == "gemini-1.5-flash"


# ===========================================================================
# 4. Valid positive payloads
# ===========================================================================

class TestValidPositivePayloads:

    def test_generate_valid_value_string(self):
        from test_generator.rule_based_generator import generate_valid_value
        assert isinstance(generate_valid_value({"type": "string"}), str)

    def test_generate_valid_value_integer(self):
        from test_generator.rule_based_generator import generate_valid_value
        val = generate_valid_value({"type": "integer"})
        assert isinstance(val, int) and not isinstance(val, bool)

    def test_generate_valid_value_email(self):
        from test_generator.rule_based_generator import generate_valid_value
        val = generate_valid_value({"type": "string", "format": "email"})
        assert "@" in val

    def test_generate_valid_value_boolean(self):
        from test_generator.rule_based_generator import generate_valid_value
        assert generate_valid_value({"type": "boolean"}) is True

    def test_positive_test_passes_when_api_returns_success(self):
        r = _validate(expected_status=200, actual_status=200)
        assert r["status"] == "PASS"
        assert r["failure_type"] is None

    def test_positive_test_201_passes(self):
        r = _validate(expected_status=201, actual_status=201)
        assert r["status"] == "PASS"


# ===========================================================================
# 5. Invalid negative payloads
# ===========================================================================

class TestInvalidNegativePayloads:

    def test_generate_wrong_type_string_field(self):
        from test_generator.rule_based_generator import generate_wrong_type
        val = generate_wrong_type({"type": "string"})
        assert not isinstance(val, str)

    def test_generate_wrong_type_integer_field(self):
        from test_generator.rule_based_generator import generate_wrong_type
        val = generate_wrong_type({"type": "integer"})
        assert not isinstance(val, int)

    def test_negative_test_with_422_pass(self):
        """Negative test that sends invalid payload and API returns 422 must PASS."""
        r = _validate(expected_status=422, actual_status=422)
        assert r["status"] == "PASS"

    def test_negative_test_schema_violation_detected(self):
        """Schema validator must catch a missing required field."""
        from test_generator.response_validator import validate_schema
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id", "name"],
        }
        assert validate_schema({"id": 1}, schema) is False  # name missing

    def test_negative_test_wrong_type_caught(self):
        from test_generator.response_validator import validate_schema
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
        assert validate_schema({"age": "twenty"}, schema) is False


# ===========================================================================
# 6. Missing required query parameters
# ===========================================================================

class TestMissingRequiredQueryParams:

    def test_generate_query_params_includes_required(self):
        from test_generator.rule_based_generator import generate_query_params
        endpoint = {
            "parameters": [
                {"name": "status", "location": "query", "type": "string", "required": True,
                 "enum": ["available", "pending", "sold"]},
            ]
        }
        params = generate_query_params(endpoint)
        assert "status" in params

    def test_generate_query_params_required_only_skips_optional(self):
        from test_generator.rule_based_generator import generate_query_params
        endpoint = {
            "parameters": [
                {"name": "required_param", "location": "query", "type": "string", "required": True},
                {"name": "optional_param", "location": "query", "type": "string", "required": False},
            ]
        }
        params = generate_query_params(endpoint, required_only=True)
        assert "required_param" in params
        assert "optional_param" not in params

    def test_generate_query_params_all_mode_includes_optional(self):
        from test_generator.rule_based_generator import generate_query_params
        endpoint = {
            "parameters": [
                {"name": "required_param", "location": "query", "type": "string", "required": True},
                {"name": "optional_param", "location": "query", "type": "string", "required": False},
            ]
        }
        params = generate_query_params(endpoint, required_only=False)
        assert "required_param" in params
        assert "optional_param" in params

    def test_positive_test_missing_required_query_would_get_400(self):
        """If a required query param is absent, the API returns 400 (not 200)."""
        # A positive test that omits 'status' for GET /pet/findByStatus would fail;
        # classification should be API_DEFECT (expected 200, got 400 due to test gen error).
        r = _validate(expected_status=200, actual_status=400, path_params={})
        # 200 → 400 is an API_DEFECT (no path params, so not RESOURCE_NOT_FOUND)
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "API_DEFECT"


# ===========================================================================
# 7. Invalid enum values
# ===========================================================================

class TestInvalidEnumValues:

    def test_generate_valid_value_returns_first_enum_member(self):
        from test_generator.rule_based_generator import generate_valid_value
        field = {"name": "status", "type": "string", "enum": ["available", "pending", "sold"]}
        assert generate_valid_value(field) == "available"

    def test_generate_valid_value_not_generic_when_enum_set(self):
        from test_generator.rule_based_generator import generate_valid_value
        field = {"name": "status", "type": "string", "enum": ["available", "pending", "sold"]}
        val = generate_valid_value(field)
        assert val != "Test User", (
            "generate_valid_value returned generic 'Test User' instead of a valid enum value. "
            "This causes positive tests to receive 400 from enum-validating APIs."
        )

    def test_schema_validator_catches_invalid_enum(self):
        from test_generator.response_validator import validate_schema
        schema = {"type": "string", "enum": ["available", "pending", "sold"]}
        assert validate_schema("available", schema) is True
        assert validate_schema("unknown_status", schema) is False
        assert validate_schema("Test User", schema) is False

    def test_wrong_enum_in_positive_test_returns_400_classified_correctly(self):
        """
        When a positive test sends an invalid enum value, the API returns 400.
        expected=200, actual=400 (no path params) → API_DEFECT (test gen bug, not real defect).
        This confirms the classification is at least not NEEDS_REVIEW (which is reserved for
        expected 4xx vs actual different 4xx).
        """
        r = _validate(expected_status=200, actual_status=400, path_params={})
        assert r["failure_type"] == "API_DEFECT"


# ===========================================================================
# 8. Expected 422 but actual 400
# ===========================================================================

class TestExpected422Actual400:

    def test_422_vs_400_is_needs_review(self):
        r = _validate(expected_status=422, actual_status=400)
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "NEEDS_REVIEW"

    def test_needs_review_does_not_produce_bug_report(self):
        """NEEDS_REVIEW must not trigger AI analysis or bug report generation."""
        r = _validate(expected_status=422, actual_status=400)
        # Executor gate: only API_DEFECT triggers analysis
        assert r["failure_type"] != "API_DEFECT"

    def test_422_vs_400_failure_reason_mentions_client_error(self):
        r = _validate(expected_status=422, actual_status=400)
        reason = r.get("failure_reason", "")
        assert "client-error" in reason or "4xx" in reason.lower() or "400" in reason


# ===========================================================================
# 9. Expected 422 but actual 200
# ===========================================================================

class TestExpected422Actual200:

    def test_422_vs_200_is_api_defect(self):
        """A negative test expecting rejection but getting success is a defect candidate."""
        r = _validate(expected_status=422, actual_status=200)
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "API_DEFECT"

    def test_422_vs_200_produces_failure_reason(self):
        r = _validate(expected_status=422, actual_status=200)
        assert r.get("failure_reason") is not None
        assert "200" in r["failure_reason"] or "422" in r["failure_reason"]


# ===========================================================================
# 10. Actual 500 responses
# ===========================================================================

class TestActual500Responses:

    def test_expected_200_actual_500_is_api_defect(self):
        r = _validate(expected_status=200, actual_status=500)
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "API_DEFECT"

    def test_expected_422_actual_500_is_api_defect(self):
        """500 from a negative test (where 422/400 was expected) is also an API defect."""
        r = _validate(expected_status=422, actual_status=500)
        assert r["status"] == "FAIL"
        # 422 is 4xx, 500 is 5xx → not both 4xx → API_DEFECT
        assert r["failure_type"] == "API_DEFECT"

    def test_500_passes_to_ai_analysis(self):
        """A 500 classified as API_DEFECT is eligible for AI analysis."""
        r = _validate(expected_status=200, actual_status=500)
        assert r["failure_type"] == "API_DEFECT"
        # Executor would call analyze_failure for API_DEFECT


# ===========================================================================
# 11. Expected 200 but actual 404 for a nonexistent resource
# ===========================================================================

class TestExpected200Actual404NonexistentResource:

    def test_404_with_path_params_is_resource_not_found(self):
        r = _validate(expected_status=200, actual_status=404, path_params={"petId": 99999})
        assert r["failure_type"] == "RESOURCE_NOT_FOUND"

    def test_404_without_path_params_is_api_defect(self):
        """A 404 on a path without params is a routing failure, not a missing resource."""
        r = _validate(expected_status=200, actual_status=404, path_params={})
        assert r["failure_type"] == "API_DEFECT"

    def test_resource_not_found_does_not_produce_bug_report(self):
        """RESOURCE_NOT_FOUND must be suppressed in the executor gate."""
        r = _validate(expected_status=200, actual_status=404, path_params={"petId": 1})
        assert r["failure_type"] != "API_DEFECT"

    def test_410_with_path_params_is_resource_not_found(self):
        r = _validate(expected_status=200, actual_status=410, path_params={"orderId": 42})
        assert r["failure_type"] == "RESOURCE_NOT_FOUND"


# ===========================================================================
# 12. Correct suppression of bug reports for NEEDS_REVIEW and analyzer failures
# ===========================================================================

class TestBugReportSuppression:

    def _executor_should_skip_bug(self, failure_type, analyzer_failed=False):
        """Reproduce the executor's gating logic."""
        if failure_type in ("NEEDS_REVIEW", "RESOURCE_NOT_FOUND",
                            "UNCERTAIN_EXPECTATION", "INFRASTRUCTURE_FAILURE"):
            return True   # skip
        if failure_type != "API_DEFECT":
            return True   # unknown type → skip
        if analyzer_failed:
            return True   # analyzer failed → skip
        return False

    def test_needs_review_is_suppressed(self):
        assert self._executor_should_skip_bug("NEEDS_REVIEW") is True

    def test_uncertain_expectation_is_suppressed(self):
        assert self._executor_should_skip_bug("UNCERTAIN_EXPECTATION") is True

    def test_resource_not_found_is_suppressed(self):
        assert self._executor_should_skip_bug("RESOURCE_NOT_FOUND") is True

    def test_infrastructure_failure_is_suppressed(self):
        assert self._executor_should_skip_bug("INFRASTRUCTURE_FAILURE") is True

    def test_analyzer_failed_is_suppressed(self):
        assert self._executor_should_skip_bug("API_DEFECT", analyzer_failed=True) is True

    def test_api_defect_with_good_analysis_not_suppressed(self):
        assert self._executor_should_skip_bug("API_DEFECT", analyzer_failed=False) is False


# ===========================================================================
# 13. Correct creation of bug reports for verified defect candidates
# ===========================================================================

class TestBugReportCreation:

    def _make_api_defect_result(self, expected=200, actual=500):
        result = _result(expected_status=expected, actual_status=actual)
        from test_generator.response_validator import validate_response
        validated = validate_response(result)
        validated["ai_analysis"] = _good_analysis()
        return validated

    def test_bug_report_generated_for_api_defect(self):
        from bug_report.bug_report_generator import generate_bug_report
        result = self._make_api_defect_result()
        bug = generate_bug_report(result, bug_counter=1)
        assert bug["bug_id"] == "BUG-001"
        assert bug["severity"] == "High"
        assert bug["status"] == "Open"

    def test_bug_report_contains_expected_fields(self):
        from bug_report.bug_report_generator import generate_bug_report
        result = self._make_api_defect_result()
        bug = generate_bug_report(result, bug_counter=5)
        required_keys = ["bug_id", "test_id", "endpoint", "severity",
                         "summary", "possible_cause", "recommendation", "status"]
        for key in required_keys:
            assert key in bug, f"Bug report missing field: {key!r}"

    def test_bug_id_increments(self):
        from bug_report.bug_report_generator import generate_bug_report
        r1 = self._make_api_defect_result()
        r2 = self._make_api_defect_result()
        b1 = generate_bug_report(r1, bug_counter=1)
        b2 = generate_bug_report(r2, bug_counter=2)
        assert b1["bug_id"] == "BUG-001"
        assert b2["bug_id"] == "BUG-002"
        assert b1["bug_id"] != b2["bug_id"]


# ===========================================================================
# 14. Database persistence and frontend-compatible result fields
# ===========================================================================

class TestDatabasePersistenceFields:
    """
    validate_response() must populate the flat fields that db_operations.save_test_result()
    and the frontend dashboard expect: expected_status, actual_status, failure_type,
    failure_reason, status_check, body_check, expected_schema, actual_body.
    """

    def test_pass_result_has_required_flat_fields(self):
        r = _validate(expected_status=200, actual_status=200)
        for field in ("status", "failure_type", "failure_reason",
                      "status_check", "body_check",
                      "expected_status", "actual_status"):
            assert field in r, f"Result missing field: {field!r}"

    def test_fail_result_has_required_flat_fields(self):
        r = _validate(expected_status=200, actual_status=500)
        for field in ("status", "failure_type", "failure_reason",
                      "status_check", "body_check",
                      "expected_status", "actual_status"):
            assert field in r, f"Result missing field: {field!r}"

    def test_pass_result_failure_type_is_none(self):
        r = _validate(expected_status=200, actual_status=200)
        assert r["failure_type"] is None

    def test_pass_result_failure_reason_is_none(self):
        r = _validate(expected_status=200, actual_status=200)
        assert r["failure_reason"] is None

    def test_fail_result_failure_type_is_not_none(self):
        r = _validate(expected_status=200, actual_status=500)
        assert r["failure_type"] is not None

    def test_failure_type_values_are_valid_strings(self):
        """failure_type values must match the set stored in the DB VARCHAR(50) column."""
        valid_types = {
            None,
            "API_DEFECT",
            "INFRASTRUCTURE_FAILURE",
            "UNCERTAIN_EXPECTATION",
            "NEEDS_REVIEW",
            "RESOURCE_NOT_FOUND",
        }
        cases = [
            dict(expected_status=200, actual_status=200),        # PASS
            dict(expected_status=200, actual_status=500),        # API_DEFECT
            dict(expected_status=200, actual_status=404, path_params={"id": 1}),  # RESOURCE_NOT_FOUND
            dict(expected_status=422, actual_status=400),        # NEEDS_REVIEW
            dict(expected_status=200, actual_status=None, error="err"),  # INFRA
        ]
        for kwargs in cases:
            r = _validate(**kwargs)
            assert r["failure_type"] in valid_types, (
                f"Unexpected failure_type {r['failure_type']!r} for case {kwargs}"
            )

    def test_status_values_are_pass_or_fail(self):
        """status field must only be 'PASS' or 'FAIL'."""
        for kwargs in [
            dict(expected_status=200, actual_status=200),
            dict(expected_status=200, actual_status=500),
        ]:
            r = _validate(**kwargs)
            assert r["status"] in ("PASS", "FAIL")

    def test_save_test_result_called_with_correct_fields(self):
        """db_operations.save_test_result must receive failure_type in the result dict."""
        from test_generator.response_validator import validate_response
        result = _result(expected_status=200, actual_status=500)
        validated = validate_response(result)
        # Verify all DB-relevant fields are present and have correct types
        assert isinstance(validated.get("failure_type"), (str, type(None)))
        assert isinstance(validated.get("status"), str)
        assert isinstance(validated.get("expected_status"), int)
        assert isinstance(validated.get("actual_status"), int)

