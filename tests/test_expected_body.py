"""
Regression tests for the null expected_body issue.

Root cause: validate_response() set result["expected_schema"] but the
frontend reads result["expected_body"] (matching the DB column name).
For live runs the two key names never matched, so the dashboard always
showed null/undefined instead of the actual schema.

Fixes applied:
1. response_validator.py: added result["expected_body"] = expected_schema
   (aliased alongside result["expected_schema"] for backward compat)
2. db_operations.py: stores None (JSON null) instead of {} when no
   schema is defined, so frontend can distinguish "schema unknown" from
   "schema is an empty object".
3. App.jsx: displays "Not specified in OpenAPI" for null/empty schemas.
"""

import sys
import os

# ---------------------------------------------------------------------------
# Path setup – mirrors conftest.py / other test files in this project
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_BACKEND = os.path.join(PROJECT_ROOT, "agent_backend")
ENGINE_ROOT   = os.path.join(AGENT_BACKEND, "engine")

for _p in (PROJECT_ROOT, AGENT_BACKEND, ENGINE_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub mysql.connector so db_operations can be imported without a live DB
from unittest.mock import MagicMock
if "mysql" not in sys.modules:
    _mock_mysql = MagicMock()
    sys.modules["mysql"] = _mock_mysql
    sys.modules["mysql.connector"] = _mock_mysql.connector

import json
import unittest
from unittest.mock import patch, MagicMock

from agent_backend.engine.test_generator.response_validator import validate_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    expected_status=200,
    actual_status=200,
    response_schema=None,
    actual_body=None,
):
    return {
        "test_id": "TC-TEST",
        "endpoint": "/test",
        "method": "GET",
        "request": {},
        "expected": {
            "status_code": expected_status,
            "response_schema": response_schema,
        },
        "actual": {
            "status_code": actual_status,
            "body": actual_body,
        },
    }


# ===========================================================================
# Tests: validate_response() now sets expected_body
# ===========================================================================

class TestExpectedBodyKeyPresent(unittest.TestCase):
    """validate_response() must expose 'expected_body' alongside 'expected_schema'."""

    def test_expected_body_key_exists_when_schema_provided(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = validate_response(_make_result(response_schema=schema))
        self.assertIn("expected_body", result,
                      "validate_response() must set result['expected_body']")

    def test_expected_body_matches_schema_value(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = validate_response(_make_result(response_schema=schema))
        self.assertEqual(result["expected_body"], schema,
                         "expected_body must equal the response_schema")

    def test_expected_body_is_none_when_no_schema(self):
        result = validate_response(_make_result(response_schema=None))
        self.assertIsNone(result["expected_body"],
                          "expected_body must be None when no schema is defined")

    def test_expected_body_key_exists_on_infrastructure_failure(self):
        """The early-return path for network errors must also set expected_body."""
        result = {
            "test_id": "TC-INF",
            "endpoint": "/test",
            "method": "GET",
            "request": {},
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": None, "body": None, "error": "Connection refused"},
        }
        validated = validate_response(result)
        self.assertIn("expected_body", validated)
        self.assertIsNone(validated["expected_body"])

    def test_expected_body_key_exists_on_infrastructure_failure_with_schema(self):
        schema = {"type": "string"}
        result = {
            "test_id": "TC-INF2",
            "endpoint": "/test",
            "method": "GET",
            "request": {},
            "expected": {"status_code": 200, "response_schema": schema},
            "actual": {"status_code": None, "body": None, "error": "Timeout"},
        }
        validated = validate_response(result)
        self.assertIn("expected_body", validated)
        self.assertEqual(validated["expected_body"], schema)

    def test_expected_schema_still_set_for_backward_compatibility(self):
        """existing code that reads expected_schema must still work."""
        schema = {"type": "array"}
        result = validate_response(_make_result(response_schema=schema))
        self.assertEqual(result["expected_schema"], schema)

    def test_expected_body_and_expected_schema_are_the_same_object(self):
        schema = {"type": "object"}
        result = validate_response(_make_result(response_schema=schema))
        self.assertIs(result["expected_body"], result["expected_schema"])


# ===========================================================================
# Tests: schema is validated (body_check != SKIP for success tests)
# ===========================================================================

class TestBodyValidationEnabled(unittest.TestCase):
    """When expected_schema is provided and status matches, body is validated."""

    def test_body_check_is_pass_when_schema_matches(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}},
                  "required": ["id"]}
        result = validate_response(_make_result(
            response_schema=schema,
            actual_body={"id": 42},
        ))
        self.assertEqual(result["body_check"], "PASS")
        self.assertEqual(result["status"], "PASS")

    def test_body_check_is_fail_when_required_field_missing(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}},
                  "required": ["id"]}
        result = validate_response(_make_result(
            response_schema=schema,
            actual_body={"name": "test"},   # missing required "id"
        ))
        self.assertEqual(result["body_check"], "FAIL")
        self.assertEqual(result["status"], "FAIL")

    def test_body_check_is_skip_when_no_schema(self):
        result = validate_response(_make_result(
            response_schema=None,
            actual_body={"anything": "here"},
        ))
        self.assertEqual(result["body_check"], "SKIP")

    def test_body_check_is_skip_for_error_status(self):
        """We do not validate success schema against 422 responses."""
        schema = {"type": "object", "properties": {"id": {"type": "integer"}},
                  "required": ["id"]}
        result = validate_response(_make_result(
            expected_status=422,
            actual_status=422,
            response_schema=schema,          # schema is for expected_status=200
            actual_body={"detail": "error"},
        ))
        # Even though schema is provided, it refers to the success response;
        # for a 422 expected result the body_check must be SKIP.
        self.assertEqual(result["body_check"], "SKIP")


# ===========================================================================
# Tests: db_operations stores expected_body correctly
# ===========================================================================

class TestDbOperationsExpectedBody(unittest.TestCase):
    """db_operations.save_test_result must store None (not {}) when schema is absent."""

    def _call_save_and_capture(self, result):
        """
        Call save_test_result with a mocked DB cursor and return the value
        that was passed to cursor.execute() for the expected_body column.
        """
        import agent_backend.db_operations as db_ops

        captured = {}

        def fake_execute(query, params):
            captured["params"] = params

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = fake_execute
        mock_cursor.lastrowid = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db_ops, "get_db_connection", return_value=mock_conn):
            db_ops.save_test_result(run_id=1, result=result)

        # expected_body is the 9th parameter (index 8, 0-based)
        # INSERT columns: run_id, test_id, method, endpoint, category,
        #                  status, failure_type, expected_status, expected_body,
        #                  actual_status, request_body, actual_body, failure_reason
        return captured["params"][8]

    def test_stores_null_when_no_schema_defined(self):
        """When expected_schema is None, expected_body in DB must be JSON null."""
        result = {
            "test_id": "TC-001",
            "method": "GET",
            "endpoint": "/test",
            "status": "PASS",
            "failure_type": None,
            "failure_reason": None,
            "expected_status": 200,
            "expected_schema": None,   # No schema defined
            "expected_body": None,
            "actual_status": 200,
            "actual_body": None,
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": 200, "body": None},
            "request": {},
        }
        raw = self._call_save_and_capture(result)
        # json.dumps(None) → "null" → stored as JSON null in DB
        self.assertEqual(json.loads(raw), None,
                         "DB must store JSON null (not {}) when schema is absent")

    def test_stores_schema_dict_when_schema_defined(self):
        """When expected_schema is a dict, it must be stored as JSON."""
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = {
            "test_id": "TC-002",
            "method": "POST",
            "endpoint": "/users",
            "status": "PASS",
            "failure_type": None,
            "failure_reason": None,
            "expected_status": 200,
            "expected_schema": schema,
            "expected_body": schema,
            "actual_status": 200,
            "actual_body": {"id": 1},
            "expected": {"status_code": 200, "response_schema": schema},
            "actual": {"status_code": 200, "body": {"id": 1}},
            "request": {},
        }
        raw = self._call_save_and_capture(result)
        self.assertEqual(json.loads(raw), schema)

    def test_stores_nested_schema_when_flat_key_missing(self):
        """
        Fallback: if 'expected_schema' is not set on result but
        expected.response_schema is, that schema must be used.
        """
        schema = {"type": "array", "items": {"type": "string"}}
        result = {
            "test_id": "TC-003",
            "method": "GET",
            "endpoint": "/list",
            "status": "PASS",
            "failure_type": None,
            "failure_reason": None,
            "expected_status": 200,
            # 'expected_schema' intentionally absent (old code path)
            "actual_status": 200,
            "actual_body": ["a", "b"],
            "expected": {"status_code": 200, "response_schema": schema},
            "actual": {"status_code": 200, "body": ["a", "b"]},
            "request": {},
        }
        raw = self._call_save_and_capture(result)
        self.assertEqual(json.loads(raw), schema)

    def test_stores_null_not_empty_dict_when_all_missing(self):
        """
        Old code stored {} when all schema sources were absent.
        New code must store None (JSON null) in that case.
        """
        result = {
            "test_id": "TC-004",
            "method": "GET",
            "endpoint": "/no-schema",
            "status": "PASS",
            "failure_type": None,
            "failure_reason": None,
            "expected_status": 200,
            "actual_status": 200,
            "actual_body": None,
            "expected": {"status_code": 200},   # no response_schema key at all
            "actual": {"status_code": 200, "body": None},
            "request": {},
        }
        raw = self._call_save_and_capture(result)
        self.assertIsNone(json.loads(raw),
                          "DB must store JSON null (not {}) when all schema sources absent")


# ===========================================================================
# Tests: openapi_parser extracts response schemas
# ===========================================================================

class TestOpenapiParserResponseSchema(unittest.TestCase):
    """get_expected_success_response must return resolved schema or None."""

    def setUp(self):
        from agent_backend.engine.test_generator.rule_based_generator import (
            get_expected_success_response,
        )
        self.get_expected_success_response = get_expected_success_response

    def _make_endpoint(self, schema=None):
        content = {}
        if schema is not None:
            content = {"application/json": {"schema": schema}}
        return {
            "method": "GET",
            "path": "/items",
            "responses": [
                {"status_code": "200", "description": "OK", "content": content}
            ],
        }

    def test_returns_none_when_no_response_schema(self):
        endpoint = self._make_endpoint(schema=None)
        result = self.get_expected_success_response(endpoint, {})
        self.assertIsNone(result)

    def test_returns_schema_dict_when_schema_defined(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        endpoint = self._make_endpoint(schema=schema)
        result = self.get_expected_success_response(endpoint, {})
        self.assertEqual(result, schema)

    def test_returns_none_when_only_error_responses(self):
        endpoint = {
            "method": "DELETE",
            "path": "/items/1",
            "responses": [
                {"status_code": "204", "description": "No Content", "content": {}},
                {"status_code": "404", "description": "Not Found", "content": {}},
            ],
        }
        # 204 has no JSON content; function should return None
        result = self.get_expected_success_response(endpoint, {})
        self.assertIsNone(result)

    def test_resolves_ref_in_response_schema(self):
        openapi_data = {
            "components": {
                "schemas": {
                    "Item": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                    }
                }
            }
        }
        schema = {"$ref": "#/components/schemas/Item"}
        endpoint = self._make_endpoint(schema=schema)
        result = self.get_expected_success_response(endpoint, openapi_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("type"), "object")


# ===========================================================================
# Tests: validate_response result dict has all expected keys
# ===========================================================================

class TestValidateResponseOutputKeys(unittest.TestCase):
    """validate_response() output must include all keys the DB and dashboard need."""

    REQUIRED_KEYS = {
        "status",
        "failure_type",
        "failure_reason",
        "status_check",
        "body_check",
        "expected_status",
        "actual_status",
        "expected_schema",
        "expected_body",    # NEW — required for live-run dashboard display
        "actual_body",
    }

    def _run(self, **kwargs):
        return validate_response(_make_result(**kwargs))

    def test_pass_result_has_all_required_keys(self):
        result = self._run(response_schema=None)
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_fail_result_has_all_required_keys(self):
        result = self._run(expected_status=200, actual_status=500)
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_infra_failure_result_has_all_required_keys(self):
        r = {
            "test_id": "TC-X",
            "endpoint": "/test",
            "method": "GET",
            "request": {},
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": None, "body": None, "error": "timeout"},
        }
        result = validate_response(r)
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_expected_body_none_for_no_schema(self):
        result = self._run(response_schema=None)
        self.assertIsNone(result["expected_body"])

    def test_expected_body_populated_for_schema(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = self._run(response_schema=schema)
        self.assertEqual(result["expected_body"], schema)


if __name__ == "__main__":
    unittest.main()
