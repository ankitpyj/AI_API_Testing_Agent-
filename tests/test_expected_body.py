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
        # Distinguish no-schema from validation failure: overall status PASS
        self.assertEqual(result["status"], "PASS")

    def test_422_response_validates_against_422_schema_when_valid(self):
        """Negative tests with documented error schema must validate the error response."""
        error_schema = {
            "type": "object",
            "properties": {
                "detail": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"msg": {"type": "string"}},
                        "required": ["msg"],
                    },
                }
            },
            "required": ["detail"],
        }
        result = validate_response(_make_result(
            expected_status=422,
            actual_status=422,
            response_schema=error_schema,
            actual_body={"detail": [{"msg": "Field required"}]},
        ))
        self.assertEqual(result["body_check"], "PASS")
        self.assertEqual(result["status"], "PASS")

    def test_422_response_fails_when_body_violates_error_schema(self):
        """
        When actual status matches expected 422, but the response body
        does not match the documented 422 schema, the test MUST FAIL.
        Never mark a test PASS only because status code matched.
        """
        error_schema = {
            "type": "object",
            "properties": {
                "detail": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"msg": {"type": "string"}},
                        "required": ["msg"],
                    },
                }
            },
            "required": ["detail"],
        }
        # Response body violates schema: detail is string instead of array
        result = validate_response(_make_result(
            expected_status=422,
            actual_status=422,
            response_schema=error_schema,
            actual_body={"detail": "string not array"},
        ))
        self.assertEqual(result["body_check"], "FAIL")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failure_type"], "API_DEFECT")
        self.assertIn("Response body does not match the expected schema",
                      result["failure_reason"])

    def test_body_check_is_skip_when_error_status_has_no_schema(self):
        """When OpenAPI defines no schema for an error status code, body_check is SKIP."""
        result = validate_response(_make_result(
            expected_status=422,
            actual_status=422,
            response_schema=None,
            actual_body={"detail": "anything"},
        ))
        self.assertEqual(result["body_check"], "SKIP")
        self.assertEqual(result["status"], "PASS")


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

    def test_resolves_swagger2_definitions_ref(self):
        """Supports #/definitions/... from Swagger 2.0 specs."""
        openapi_data = {
            "definitions": {
                "Pet": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            }
        }
        schema = {"$ref": "#/definitions/Pet"}
        endpoint = self._make_endpoint(schema=schema)
        result = self.get_expected_success_response(endpoint, openapi_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("type"), "object")

    def test_resolves_swagger2_direct_schema_in_response(self):
        """Supports responses that have schema directly instead of content.application/json."""
        endpoint = {
            "method": "GET",
            "path": "/pets",
            "responses": [
                {
                    "status_code": "200",
                    "description": "OK",
                    "schema": {"type": "array", "items": {"type": "string"}},
                }
            ],
        }
        result = self.get_expected_success_response(endpoint, {})
        self.assertIsNotNone(result)
        self.assertEqual(result.get("type"), "array")

    def test_get_expected_response_for_status_422(self):
        """get_expected_response_for_status extracts 422 schema properly."""
        from agent_backend.engine.test_generator.rule_based_generator import (
            get_expected_response_for_status,
        )
        error_schema = {"type": "object", "properties": {"detail": {"type": "string"}}}
        endpoint = {
            "method": "POST",
            "path": "/login",
            "responses": [
                {"status_code": "200", "content": {"application/json": {"schema": {"type": "object"}}}},
                {"status_code": "422", "content": {"application/json": {"schema": error_schema}}},
            ],
        }
        schema = get_expected_response_for_status(endpoint, {}, 422)
        self.assertEqual(schema, error_schema)


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


# ===========================================================================
# Tests: Advanced JSON Schema Features & Violation Reporting
# ===========================================================================

class TestAdvancedSchemaValidation(unittest.TestCase):
    """Verifies schema validation features: unconstrained schemas, allOf, additionalProperties, multi-types."""

    def test_unconstrained_schema_accepts_null(self):
        """A schema with no 'type' keyword (e.g. {'title': 'Input'}) allows any value including null."""
        from agent_backend.engine.test_generator.response_validator import validate_schema
        self.assertTrue(validate_schema(None, {"title": "Input"}))
        self.assertTrue(validate_schema("string_val", {"title": "Input"}))
        self.assertTrue(validate_schema(12345, {"title": "Input"}))
        self.assertTrue(validate_schema({"nested": "dict"}, {"title": "Input"}))

    def test_fastapi_422_with_null_input_passes_schema(self):
        """
        TC-012, TC-013, TC-014, TC-028, TC-029:
        FastAPI validation error responses include {'input': None} when null is submitted.
        This must validate successfully against HTTPValidationError.
        """
        from agent_backend.engine.test_generator.response_validator import validate_schema
        http_val_err_schema = {
            "type": "object",
            "properties": {
                "detail": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "loc": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
                            "msg": {"type": "string"},
                            "type": {"type": "string"},
                            "input": {"title": "Input"},
                            "ctx": {"type": "object"},
                        },
                        "required": ["loc", "msg", "type"],
                    },
                }
            },
        }
        # Actual responses from TC-012 and TC-028
        tc12_resp = {"detail": [{"type": "string_type", "loc": ["body", "name"], "msg": "Input should be a valid string", "input": None}]}
        tc28_resp = {"detail": [{"type": "string_type", "loc": ["body", "email"], "msg": "Input should be a valid string", "input": None}]}

        self.assertTrue(validate_schema(tc12_resp, http_val_err_schema))
        self.assertTrue(validate_schema(tc28_resp, http_val_err_schema))

    def test_all_of_validation(self):
        """allOf must pass when all subschemas match, fail when any fails."""
        from agent_backend.engine.test_generator.response_validator import validate_schema
        schema = {
            "allOf": [
                {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            ]
        }
        self.assertTrue(validate_schema({"id": 1, "name": "Alice"}, schema))
        self.assertFalse(validate_schema({"id": 1}, schema))  # missing name
        self.assertFalse(validate_schema({"name": "Alice"}, schema))  # missing id

    def test_additional_properties_false_rejects_extra(self):
        """additionalProperties: False must reject unexpected properties."""
        from agent_backend.engine.test_generator.response_validator import validate_schema
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "additionalProperties": False,
        }
        self.assertTrue(validate_schema({"id": 1}, schema))
        self.assertFalse(validate_schema({"id": 1, "extra_field": "disallowed"}, schema))

    def test_additional_properties_schema_validates_values(self):
        """additionalProperties with a schema dictionary validates map/dict entries."""
        from agent_backend.engine.test_generator.response_validator import validate_schema
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "additionalProperties": {"type": "string"},
        }
        self.assertTrue(validate_schema({"id": 1, "tag1": "valid_string"}, schema))
        self.assertFalse(validate_schema({"id": 1, "tag1": 12345}, schema))  # 12345 is not string

    def test_multi_type_list_support(self):
        """OpenAPI 3.1 type: ['string', 'null'] allows both strings and null."""
        from agent_backend.engine.test_generator.response_validator import validate_schema
        schema = {"type": ["string", "null"]}
        self.assertTrue(validate_schema("hello", schema))
        self.assertTrue(validate_schema(None, schema))
        self.assertFalse(validate_schema(12345, schema))

    def test_schema_violations_populated_in_result_on_failure(self):
        """When schema validation fails, result must contain detailed schema_violations."""
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        result = _make_result(
            response_schema=schema,
            actual_body={"wrong_field": "val"},  # missing id
        )
        validated = validate_response(result)
        self.assertEqual(validated["body_check"], "FAIL")
        self.assertEqual(validated["status"], "FAIL")
        self.assertIn("schema_violations", validated)
        self.assertTrue(len(validated["schema_violations"]) > 0)
        self.assertTrue(any("id" in v for v in validated["schema_violations"]))
        # failure_reason must describe the exact mismatch
        self.assertIn("missing required property", validated["failure_reason"])


if __name__ == "__main__":
    unittest.main()
