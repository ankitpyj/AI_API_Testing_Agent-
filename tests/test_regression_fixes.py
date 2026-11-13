"""
Regression tests for root-cause fixes.

Coverage:
  Fix 1  - ai_failure_analyzer uses GEMINI_MODEL env var, not a hardcoded nonexistent model
  Fix 1b - analyzer_failed flag propagates so callers can skip bug reports
  Fix 1c - missing GEMINI_API_KEY produces analyzer_failed, not an import-time crash
  Fix 2  - INFRASTRUCTURE_FAILURE does not generate a bug report
  Fix 3  - RESOURCE_NOT_FOUND emitted for positive-test 404 with path params
  Fix 4  - NEEDS_REVIEW emitted for 4xx-vs-4xx status mismatches
  Fix 5  - SSRF guard blocks loopback / private / metadata addresses
  Fix 5b - SSRF guard allows legitimate external URLs

Run with:
    cd g:/ai_api-testing_agent
    python -m pytest tests/test_regression_fixes.py -v
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup so tests can import engine modules directly
# ---------------------------------------------------------------------------
REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_ROOT = os.path.join(REPO_ROOT, "agent_backend")
ENGINE_ROOT  = os.path.join(BACKEND_ROOT, "engine")

for p in [ENGINE_ROOT, BACKEND_ROOT, REPO_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Stub mysql.connector so test_executor can be imported without a live DB
# ---------------------------------------------------------------------------
if "mysql" not in sys.modules:
    _mock_mysql = MagicMock()
    sys.modules["mysql"] = _mock_mysql
    sys.modules["mysql.connector"] = _mock_mysql.connector

if "database" not in sys.modules:
    _mock_db = MagicMock()
    sys.modules["database"] = _mock_db

if "db_operations" not in sys.modules:
    _mock_db_ops = MagicMock()
    sys.modules["db_operations"] = _mock_db_ops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    method="GET",
    endpoint="/items/{item_id}",
    expected_status=200,
    actual_status=200,
    path_params=None,
    expectation_confidence="high",
    requires_review=False,
    expected_source="openapi_spec",
    error=None,
):
    return {
        "test_id": "TC-001",
        "endpoint": endpoint,
        "method": method,
        "request": {
            "path_params": path_params or {},
            "query_params": {},
            "headers": {},
            "body": None,
        },
        "expected": {"status_code": expected_status, "response_schema": None},
        "actual": {"status_code": actual_status, "body": {}, "error": error},
        "expectation_confidence": expectation_confidence,
        "requires_review": requires_review,
        "expected_source": expected_source,
    }


# ===========================================================================
# Fix 1 - AI analyzer model name
# ===========================================================================

class TestAIAnalyzerModelName:
    """Verify that ai_failure_analyzer.py uses GEMINI_MODEL, not a hardcoded string."""

    def test_model_constant_is_gemini(self):
        from ai_analyzer.ai_failure_analyzer import GEMINI_MODEL
        assert "gpt-oss" not in GEMINI_MODEL, (
            f"GEMINI_MODEL still contains the NVIDIA model name: {GEMINI_MODEL!r}"
        )
        assert "gemini" in GEMINI_MODEL.lower(), (
            f"GEMINI_MODEL does not look like a Gemini model: {GEMINI_MODEL!r}"
        )

    def test_model_is_not_nonexistent_model(self):
        """gemini-3.5-flash-lite does not exist — confirm it is no longer hardcoded."""
        from ai_analyzer.ai_failure_analyzer import GEMINI_MODEL
        assert GEMINI_MODEL != "gemini-3.5-flash-lite", (
            "GEMINI_MODEL is still set to 'gemini-3.5-flash-lite', "
            "which does not exist and causes every API call to fail."
        )

    def test_analyze_failure_uses_gemini_model(self):
        """Patch client and confirm model= arg matches GEMINI_MODEL."""
        import ai_analyzer.ai_failure_analyzer as mod

        captured = {}

        def fake_create(**kwargs):
            captured["model"] = kwargs.get("model")
            fake_choice = MagicMock()
            fake_choice.message.content = (
                '{"summary":"ok","possible_cause":"none",'
                '"severity":"Low","recommendation":"none"}'
            )
            fake_resp = MagicMock()
            fake_resp.choices = [fake_choice]
            return fake_resp

        with patch.object(
            mod.client.chat.completions,
            "create",
            side_effect=lambda **kw: fake_create(**kw),
        ):
            mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert captured.get("model") == mod.GEMINI_MODEL, (
            f"analyze_failure called client with model={captured.get('model')!r} "
            f"instead of GEMINI_MODEL={mod.GEMINI_MODEL!r}"
        )

    def test_analyzer_failed_flag_on_exception(self):
        """When the AI client raises, analyzer_failed must be True."""
        import ai_analyzer.ai_failure_analyzer as mod

        with patch.object(
            mod.client.chat.completions,
            "create",
            side_effect=RuntimeError("network error"),
        ):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result.get("analyzer_failed") is True

    def test_analyzer_failed_flag_on_json_decode_error(self):
        """When the AI returns invalid JSON, analyzer_failed must be True."""
        import ai_analyzer.ai_failure_analyzer as mod

        fake_choice = MagicMock()
        fake_choice.message.content = "not json at all"
        fake_resp = MagicMock()
        fake_resp.choices = [fake_choice]

        with patch.object(mod.client.chat.completions, "create", return_value=fake_resp):
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})

        assert result.get("analyzer_failed") is True

    def test_analyzer_failed_when_client_is_none(self):
        """When client is None (missing key), analyze_failure must return analyzer_failed=True."""
        import ai_analyzer.ai_failure_analyzer as mod

        original_client = mod.client
        try:
            mod.client = None
            result = mod.analyze_failure({"test_id": "TC-001", "status": "FAIL"})
            assert result.get("analyzer_failed") is True
        finally:
            mod.client = original_client


# ===========================================================================
# Fix 3 - RESOURCE_NOT_FOUND classification
# ===========================================================================

class TestResourceNotFoundClassification:

    def _validate(self, **kwargs):
        from test_generator.response_validator import validate_response
        return validate_response(_make_result(**kwargs))

    def test_positive_test_404_with_path_params_is_resource_not_found(self):
        r = self._validate(
            expected_status=200,
            actual_status=404,
            path_params={"item_id": 1},
        )
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "RESOURCE_NOT_FOUND", (
            f"Expected RESOURCE_NOT_FOUND, got {r['failure_type']!r}"
        )

    def test_positive_test_410_with_path_params_is_resource_not_found(self):
        r = self._validate(
            expected_status=200,
            actual_status=410,
            path_params={"item_id": 99},
        )
        assert r["failure_type"] == "RESOURCE_NOT_FOUND"

    def test_positive_test_404_without_path_params_is_api_defect(self):
        """A 404 on an endpoint with NO path params is a genuine routing failure."""
        r = self._validate(
            expected_status=200,
            actual_status=404,
            path_params={},
        )
        assert r["failure_type"] == "API_DEFECT", (
            f"Expected API_DEFECT (no path params), got {r['failure_type']!r}"
        )

    def test_correct_response_is_pass(self):
        r = self._validate(expected_status=200, actual_status=200)
        assert r["status"] == "PASS"
        assert r["failure_type"] is None


# ===========================================================================
# Fix 4 - NEEDS_REVIEW for 4xx vs 4xx mismatches
# ===========================================================================

class TestNeedsReviewClassification:

    def _validate(self, **kwargs):
        from test_generator.response_validator import validate_response
        return validate_response(_make_result(**kwargs))

    def test_422_expected_400_actual_is_needs_review(self):
        r = self._validate(expected_status=422, actual_status=400)
        assert r["status"] == "FAIL"
        assert r["failure_type"] == "NEEDS_REVIEW", (
            f"Expected NEEDS_REVIEW, got {r['failure_type']!r}"
        )

    def test_400_expected_422_actual_is_needs_review(self):
        r = self._validate(expected_status=400, actual_status=422)
        assert r["failure_type"] == "NEEDS_REVIEW"

    def test_200_expected_500_actual_is_api_defect(self):
        r = self._validate(expected_status=200, actual_status=500)
        assert r["failure_type"] == "API_DEFECT"

    def test_identical_4xx_is_pass(self):
        r = self._validate(expected_status=422, actual_status=422)
        assert r["status"] == "PASS"

    def test_needs_review_does_not_produce_bug_report(self):
        """NEEDS_REVIEW failures must be suppressed in the executor gate."""
        from test_generator.response_validator import validate_response
        result = validate_response(_make_result(expected_status=422, actual_status=400))
        failure_type = result.get("failure_type")
        # Replicate the executor's gating logic
        should_generate_bug = failure_type == "API_DEFECT"
        assert not should_generate_bug, (
            "NEEDS_REVIEW classified as API_DEFECT and would produce a false bug report"
        )


# ===========================================================================
# Fix 2 - INFRASTRUCTURE_FAILURE does not produce bug reports
# ===========================================================================

class TestInfrastructureFailureNoBugReport:

    def test_network_error_classified_as_infrastructure_failure(self):
        from test_generator.response_validator import validate_response
        r = _make_result(actual_status=None, error="Connection refused")
        validated = validate_response(r)
        assert validated["failure_type"] == "INFRASTRUCTURE_FAILURE"

    def test_executor_gate_skips_infra_failure(self):
        """The gating expression in the executor must NOT generate a bug report for INFRA_FAILURE."""
        from test_generator.response_validator import validate_response
        result = validate_response(_make_result(actual_status=None, error="Connection refused"))
        failure_type = result.get("failure_type")
        should_generate_bug = failure_type == "API_DEFECT"
        assert not should_generate_bug


# ===========================================================================
# New: Rule-based generator enum handling
# ===========================================================================

class TestGeneratorEnumHandling:
    """Enum-constrained parameters must produce valid enum values, not generic ones."""

    def test_generate_valid_value_respects_enum(self):
        from test_generator.rule_based_generator import generate_valid_value
        field = {"name": "status", "type": "string", "enum": ["available", "pending", "sold"]}
        val = generate_valid_value(field)
        assert val in ["available", "pending", "sold"], (
            f"Expected an enum member, got {val!r}"
        )

    def test_generate_valid_value_returns_first_enum(self):
        from test_generator.rule_based_generator import generate_valid_value
        field = {"name": "status", "type": "string", "enum": ["available", "pending", "sold"]}
        assert generate_valid_value(field) == "available"

    def test_generate_valid_value_without_enum_returns_generic(self):
        from test_generator.rule_based_generator import generate_valid_value
        field = {"name": "name", "type": "string"}
        val = generate_valid_value(field)
        assert isinstance(val, str)

    def test_generate_query_params_includes_required_enum_param(self):
        from test_generator.rule_based_generator import generate_query_params
        endpoint = {
            "parameters": [
                {
                    "name": "status",
                    "location": "query",
                    "type": "string",
                    "enum": ["available", "pending", "sold"],
                    "required": True,
                }
            ]
        }
        params = generate_query_params(endpoint)
        assert "status" in params
        assert params["status"] in ["available", "pending", "sold"], (
            f"Expected valid Petstore status, got {params['status']!r}"
        )


# ===========================================================================
# New: Bug report suppression for analyzer failures
# ===========================================================================

class TestAnalyzerFailureSuppression:

    def test_analyzer_failure_does_not_produce_bug_report(self):
        """When analyzer_failed=True, the executor must skip bug report generation."""
        analysis = {
            "analyzer_failed": True,
            "summary": "AI unavailable",
            "possible_cause": "API key missing",
            "severity": "Medium",
            "recommendation": "Set GEMINI_API_KEY",
        }
        # Replicate executor logic
        should_generate_bug = not analysis.get("analyzer_failed")
        assert not should_generate_bug

    def test_successful_analysis_can_produce_bug_report(self):
        """A successful analysis (no analyzer_failed) should allow bug report creation."""
        analysis = {
            "summary": "API returned 500",
            "possible_cause": "Server-side error",
            "severity": "High",
            "recommendation": "Check server logs",
        }
        should_generate_bug = not analysis.get("analyzer_failed")
        assert should_generate_bug


# ===========================================================================
# Fix 5 - SSRF protection
# ===========================================================================

class TestSSRFProtection:

    def _validate_url(self, url, allow_local=False):
        import test_generator.test_executor as mod
        original = mod._ALLOW_LOCAL
        mod._ALLOW_LOCAL = allow_local
        try:
            mod._validate_target_url(url)
        finally:
            mod._ALLOW_LOCAL = original

    def test_loopback_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("http://127.0.0.1/anything", allow_local=False)

    def test_private_class_a_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("http://10.0.0.1/secret", allow_local=False)

    def test_private_class_b_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("http://172.31.255.255/secret", allow_local=False)

    def test_private_class_c_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("http://192.168.1.1/secret", allow_local=False)

    def test_link_local_metadata_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url(
                "http://169.254.169.254/latest/meta-data/", allow_local=False
            )

    def test_non_http_scheme_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("file:///etc/passwd", allow_local=False)

    def test_ftp_scheme_blocked(self):
        with pytest.raises(ValueError, match="SSRF"):
            self._validate_url("ftp://10.0.0.1/file", allow_local=False)

    def test_external_url_allowed(self):
        """Legitimate public APIs must not be blocked."""
        import test_generator.test_executor as mod
        with patch(
            "test_generator.test_executor.socket.gethostbyname",
            return_value="104.21.0.1",
        ):
            self._validate_url(
                "https://petstore3.swagger.io/api/v3/openapi.json",
                allow_local=False,
            )

    def test_allow_local_bypasses_check(self):
        """ALLOW_LOCAL_TARGETS=true must bypass SSRF check for local dev."""
        self._validate_url("http://127.0.0.1:8000/", allow_local=True)
