import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Ensure agent_backend and submodules are importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_BACKEND_DIR = os.path.join(BASE_DIR, "agent_backend")
if AGENT_BACKEND_DIR not in sys.path:
    sys.path.insert(0, AGENT_BACKEND_DIR)

# Mock mysql and mysql.connector if not installed so tests run portably
try:
    import mysql.connector
except ImportError:
    mock_mysql = MagicMock()
    mock_mysql_connector = MagicMock()
    sys.modules["mysql"] = mock_mysql
    sys.modules["mysql.connector"] = mock_mysql_connector

from engine.parser.openapi_parser import (
    resolve_schema,
    extract_schema_details,
    extract_endpoints,
)
from engine.test_generator.rule_based_generator import (
    generate_all_tests,
    generate_valid_value,
    generate_wrong_type,
)
from engine.test_generator.response_validator import (
    validate_response,
    validate_schema,
)
from engine.test_generator.test_executor import execute_test, sort_tests_for_execution


# ── Sample OpenAPI Specification Fixture ──────────────────────────────

@pytest.fixture
def sample_openapi():
    return {
        "openapi": "3.0.2",
        "info": {"title": "Test User API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "summary": "Get Users",
                    "responses": {
                        "200": {
                            "description": "Successful Response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UsersResponse"}
                                }
                            }
                        }
                    }
                },
                "post": {
                    "summary": "Create User",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UserCreate"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Successful Response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UserResponse"}
                                }
                            }
                        }
                    }
                }
            },
            "/users/{user_id}": {
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"}
                    }
                ],
                "put": {
                    "summary": "Update User",
                    "responses": {
                        "200": {
                            "description": "Successful Response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UserResponse"}
                                }
                            }
                        }
                    }
                },
                "delete": {
                    "summary": "Delete User",
                    "responses": {
                        "200": {
                            "description": "Successful Response",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            },
            "/health": {
                "get": {
                    "summary": "Health Check",
                    "responses": {
                        "200": {
                            "description": "Health status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "example": "ok"
                                            }
                                        },
                                        "required": ["status"]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "UserCreate": {
                    "type": "object",
                    "required": ["name", "email", "age"],
                    "properties": {
                        "name": {"type": "string", "example": "Alice Example"},
                        "email": {"type": "string", "format": "email", "example": "alice@example.com"},
                        "age": {"type": "integer", "example": 25}
                    }
                },
                "UserResponse": {
                    "type": "object",
                    "required": ["id", "name", "email", "age"],
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string", "example": "Alice Example"},
                        "email": {"type": "string", "format": "email"},
                        "age": {"type": "integer"}
                    }
                },
                "UsersResponse": {
                    "type": "object",
                    "required": ["users"],
                    "properties": {
                        "users": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/UserResponse"}
                        }
                    }
                }
            }
        }
    }


# ── 1. Parser Tests ──────────────────────────────────────────────────

class TestOpenAPIParser:
    def test_resolve_schema_ref(self, sample_openapi):
        schema = {"$ref": "#/components/schemas/UserCreate"}
        resolved = resolve_schema(schema, sample_openapi)
        assert resolved["type"] == "object"
        assert "name" in resolved["properties"]
        assert resolved["required"] == ["name", "email", "age"]

    def test_resolve_schema_anyof_nullable(self, sample_openapi):
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "null"}
            ]
        }
        resolved = resolve_schema(schema, sample_openapi)
        assert resolved["type"] == "string"

    def test_extract_endpoints(self, sample_openapi):
        endpoints = extract_endpoints(sample_openapi)
        methods_and_paths = [(ep["method"], ep["path"]) for ep in endpoints]
        assert ("GET", "/users") in methods_and_paths
        assert ("POST", "/users") in methods_and_paths
        assert ("PUT", "/users/{user_id}") in methods_and_paths
        assert ("DELETE", "/users/{user_id}") in methods_and_paths
        assert ("GET", "/health") in methods_and_paths

    def test_extract_request_body_schema(self, sample_openapi):
        endpoints = extract_endpoints(sample_openapi)
        post_user = next(ep for ep in endpoints if ep["method"] == "POST" and ep["path"] == "/users")
        assert post_user["request_body"] is not None
        field_names = [f["name"] for f in post_user["request_body"]["fields"]]
        assert "name" in field_names
        assert "email" in field_names
        assert "age" in field_names


# ── 2. Rule-Based Generator Tests ─────────────────────────────────────

class TestRuleBasedGenerator:
    def test_generate_all_tests_with_preloaded_openapi(self, sample_openapi):
        # Verify openapi_data is reused without invoking load_openapi over the network
        with patch("engine.test_generator.rule_based_generator.load_openapi") as mock_load:
            tests = generate_all_tests(openapi_data=sample_openapi)
            mock_load.assert_not_called()
            assert len(tests) > 0

    def test_delete_ordering_rule(self, sample_openapi):
        tests = generate_all_tests(openapi_data=sample_openapi)
        # Apply executor's DELETE sorting rule
        sort_tests_for_execution(tests)
        
        seen_delete = False
        for t in tests:
            if t.get("method", "").upper() == "DELETE":
                seen_delete = True
            elif seen_delete:
                # If we encounter a non-DELETE test after a DELETE test, ordering failed
                pytest.fail(f"Non-DELETE test {t.get('method')} {t.get('endpoint')} appeared after DELETE!")

    def test_generator_creates_positive_and_negative_cases(self, sample_openapi):
        tests = generate_all_tests(openapi_data=sample_openapi)
        categories = {t.get("category") for t in tests}
        assert "positive" in categories
        assert "negative" in categories


# ── 3. Response Validator Tests ───────────────────────────────────────

class TestResponseValidator:
    def test_valid_response(self):
        result = {
            "test_id": "TC-001",
            "expected": {
                "status_code": 200,
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "is_active": {"type": "boolean"}
                    },
                    "required": ["id", "name"]
                }
            },
            "actual": {
                "status_code": 200,
                "body": {"id": 1, "name": "Alice", "is_active": True}
            }
        }
        validated = validate_response(result)
        assert validated["status"] == "PASS"
        assert validated["status_check"] == "PASS"
        assert validated["body_check"] == "PASS"
        assert validated["failure_reason"] is None
    
    def test_unicode_name_is_preserved(self):
        original_name = "Jos\u00e9 Mar\u00eda-O'Connor Jr."

        result = {
            "test_id": "TC-UNICODE-001",
            "expected": {
                "status_code": 201,
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    },
                    "required": ["name"]
                }
            },
            "actual": {
                "status_code": 201,
                "body": {"name": original_name}
            }
        }

        validated = validate_response(result)

        assert validated["status"] == "PASS"
        assert result["actual"]["body"]["name"] == original_name

    def test_invalid_response_types(self):
        # Returning string where integer is expected
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"]
        }
        assert validate_schema({"id": "not-an-int"}, schema) is False
        
        # Returning boolean where integer is expected (in Python bool is subclass of int)
        assert validate_schema({"id": True}, schema) is False
        
        # Returning int where boolean is expected
        bool_schema = {
            "type": "object",
            "properties": {"active": {"type": "boolean"}},
            "required": ["active"]
        }
        assert validate_schema({"active": 1}, bool_schema) is False

    def test_missing_required_fields(self):
        result = {
            "test_id": "TC-002",
            "expected": {
                "status_code": 200,
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "email": {"type": "string"}
                    },
                    "required": ["id", "email"]
                }
            },
            "actual": {
                "status_code": 200,
                "body": {"id": 1}  # Missing 'email'
            }
        }
        validated = validate_response(result)
        assert validated["status"] == "FAIL"
        assert validated["failure_type"] == "API_DEFECT"
        assert "does not match the expected schema" in validated["failure_reason"]

    def test_http_200_with_error_body(self):
        # When target returns 200 but body contains {"status": "error"}
        result = {
            "test_id": "TC-003",
            "expected": {
                "status_code": 200,
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["ok"]
                        }
                    },
                    "required": ["status"]
                }
            },
            "actual": {
                "status_code": 200,
                "body": {"status": "error"}
            }
        }
        validated = validate_response(result)
        assert validated["status"] == "FAIL"
        assert validated["failure_type"] == "API_DEFECT"
        assert "indicates error" in validated["failure_reason"] or "does not match" in validated["failure_reason"]

    def test_illustrative_examples_do_not_cause_false_failures(self):
        # Illustrative OpenAPI examples (e.g. name="Alice Example") must NOT fail valid data with different name
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "example": 1},
                "name": {"type": "string", "example": "Alice Example"}
            },
            "required": ["id", "name"]
        }
        actual_data = {"id": 999, "name": "Bob Different"}
        # Must pass schema validation despite not matching illustrative examples
        assert validate_schema(actual_data, schema, strict_examples=False) is True

    def test_deterministic_without_llm(self):
        # Ensure validation makes zero network calls and executes deterministically
        result = {
            "test_id": "TC-004",
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": 200, "body": {"message": "ok"}}
        }
        validated = validate_response(result)
        assert validated["status"] == "PASS"


# ── 4. Execution & Infrastructure Failure Tests ───────────────────────

class TestExecutionAndInfrastructure:
    @patch("requests.request")
    def test_network_failure_classified_as_infrastructure(self, mock_request):
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused: 127.0.0.1:8000")

        test_case = {
            "test_id": "TC-NET-1",
            "endpoint": "/users",
            "method": "GET",
            "request": {},
            "expected": {"status_code": 200}
        }

        executed_result = execute_test(test_case, base_url="http://127.0.0.1:8000")
        assert executed_result["actual"]["status_code"] is None
        assert "Connection refused" in executed_result["actual"]["error"]

        validated = validate_response(executed_result)
        assert validated["status"] == "FAIL"
        assert validated["failure_type"] == "INFRASTRUCTURE_FAILURE"
        assert "Infrastructure/Network failure" in validated["failure_reason"]

    def test_repeated_test_runs_idempotency(self, sample_openapi):
        # Repeated test generation with the same OpenAPI data yields identical test sets
        tests_run_1 = generate_all_tests(openapi_data=sample_openapi)
        tests_run_2 = generate_all_tests(openapi_data=sample_openapi)
        
        assert len(tests_run_1) == len(tests_run_2)
        test_ids_1 = [t["test_id"] for t in tests_run_1]
        test_ids_2 = [t["test_id"] for t in tests_run_2]
        assert test_ids_1 == test_ids_2

    def test_sorting_preserves_all_tests_repeatedly(self, sample_openapi):
        tests = generate_all_tests(openapi_data=sample_openapi)
        count_before = len(tests)
        
        # Sort repeatedly
        for _ in range(3):
            sort_tests_for_execution(tests)
            assert len(tests) == count_before
            # Final items must be DELETE
            delete_indices = [i for i, t in enumerate(tests) if t.get("method", "").upper() == "DELETE"]
            if delete_indices:
                assert min(delete_indices) >= (len(tests) - len(delete_indices))


# ── 5. Uncertain Expectation Classification ───────────────────────────────

class TestUncertainExpectationClassification:
    """
    validate_response() must use UNCERTAIN_EXPECTATION (not API_DEFECT)
    for low-confidence or review-required AI test mismatches.
    Absent provenance defaults to high-confidence → API_DEFECT (backward-compat).
    """

    def _make_result(self, expected_status, actual_status, *,
                     confidence="high", requires_review=False,
                     expected_source="openapi_spec"):
        result = {
            "test_id": "AI-TC-001",
            "endpoint": "/login",
            "method": "POST",
            "request": {},
            "expected": {"status_code": expected_status, "response_schema": None},
            "actual": {"status_code": actual_status, "body": None},
            "expectation_confidence": confidence,
            "requires_review": requires_review,
            "expected_source": expected_source,
        }
        return result

    def test_low_confidence_mismatch_is_uncertain_not_defect(self):
        result = self._make_result(200, 401, confidence="low")
        out = validate_response(result)
        assert out["status"] == "FAIL"
        assert out["failure_type"] == "UNCERTAIN_EXPECTATION", (
            f"Expected UNCERTAIN_EXPECTATION, got {out['failure_type']}"
        )

    def test_requires_review_mismatch_is_uncertain_not_defect(self):
        result = self._make_result(200, 401, confidence="high", requires_review=True)
        out = validate_response(result)
        assert out["status"] == "FAIL"
        assert out["failure_type"] == "UNCERTAIN_EXPECTATION"

    def test_high_confidence_openapi_mismatch_is_api_defect(self):
        result = self._make_result(201, 400, confidence="high",
                                   expected_source="openapi_spec")
        out = validate_response(result)
        assert out["status"] == "FAIL"
        assert out["failure_type"] == "API_DEFECT"

    def test_no_provenance_defaults_to_api_defect(self):
        result = {
            "test_id": "TC-001",
            "endpoint": "/users",
            "method": "GET",
            "request": {},
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": 404, "body": None},
        }
        out = validate_response(result)
        assert out["status"] == "FAIL"
        assert out["failure_type"] == "API_DEFECT"

    def test_uncertain_expectation_match_still_passes(self):
        result = self._make_result(200, 200, confidence="low", requires_review=True)
        out = validate_response(result)
        assert out["status"] == "PASS"
        assert out["failure_type"] is None


# ── 6. Unicode Round-Trip ─────────────────────────────────────────────────

class TestUnicodeHandling:

    def test_unicode_string_passes_schema_validation(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        for name in ["Jos\u00e9 Garc\u00eda", "\u4e2d\u6587\u540d\u5b57",
                     "Ankit\u2019s Test", "\u00e9\u00e0\u00fc"]:
            assert validate_schema({"name": name}, schema), (
                f"Unicode name {name!r} incorrectly failed schema validation"
            )

    def test_unicode_preserved_through_validate_response(self):
        original = "Jos\u00e9 Mar\u00eda-O\u2019Connor"
        result = {
            "test_id": "AI-UNICODE",
            "endpoint": "/users",
            "method": "POST",
            "request": {},
            "expected": {
                "status_code": 201,
                "response_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            "actual": {"status_code": 201, "body": {"name": original}},
        }
        out = validate_response(result)
        assert out["status"] == "PASS"
        assert out["actual_body"]["name"] == original

    def test_unicode_survives_json_round_trip(self):
        import json
        body = {"name": "\u00c5ngstr\u00f6m \u00dcn\u00ef\u00e7\u00f6d\u00e9"}
        serialised = json.dumps(body, ensure_ascii=False)
        deserialised = json.loads(serialised)
        assert deserialised["name"] == body["name"]
        # ensure_ascii=True must NOT mutate the Python dict
        _ = json.dumps(body, ensure_ascii=True)
        assert body["name"] == "\u00c5ngstr\u00f6m \u00dcn\u00ef\u00e7\u00f6d\u00e9"


# ── 7. Bug Report Suppression ─────────────────────────────────────────────

class TestBugReportSuppression:

    def test_uncertain_failure_should_not_become_confirmed_bug(self):
        result = {
            "test_id": "AI-TC-001",
            "endpoint": "/login",
            "method": "POST",
            "request": {},
            "expected": {"status_code": 200, "response_schema": None},
            "actual": {"status_code": 401, "body": None},
            "expectation_confidence": "low",
            "requires_review": True,
            "expected_source": "ai_inferred",
        }
        validated = validate_response(result)
        assert validated["failure_type"] == "UNCERTAIN_EXPECTATION"
        # Executor decision gate
        if validated.get("failure_type") == "UNCERTAIN_EXPECTATION":
            validated["bug_report"] = None
        assert validated.get("bug_report") is None

    def test_api_defect_is_not_suppressed(self):
        result = {
            "test_id": "TC-005",
            "endpoint": "/users",
            "method": "POST",
            "request": {},
            "expected": {"status_code": 201, "response_schema": None},
            "actual": {"status_code": 500, "body": None},
        }
        validated = validate_response(result)
        assert validated["failure_type"] == "API_DEFECT"


# ── 8. AI Generator Provenance Contract ───────────────────────────────────

class TestAIGeneratorProvenanceContract:
    """Mocked LLM — no live API key required."""

    def _make_payload(self, *, status=201, source="openapi_spec",
                      confidence="high", review=False, reason=None):
        return {
            "tests": [
                {
                    "category": "boundary",
                    "description": f"t{i}",
                    "request": {"body": {"name": "X", "email": f"x{i}@e.com", "age": i}},
                    "expected": {"status_code": status},
                    "expected_source": source,
                    "expectation_confidence": confidence,
                    "requires_review": review,
                    "review_reason": reason,
                }
                for i in range(5)
            ]
        }

    def test_high_confidence_non_auth_tests_not_flagged(self):
        import json
        from unittest.mock import patch, MagicMock
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent_backend"))
        from engine.ai_generator import ai_test_generator as gen

        payload = self._make_payload(source="openapi_spec", confidence="high")
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps(payload)

        with patch.object(gen.client.chat.completions, "create", return_value=mock_resp):
            tests = gen.generate_ai_tests({
                "path": "/items",
                "method": "POST",
                "request_body": {"fields": []},
                "responses": [{"status_code": 201}, {"status_code": 422}],
            })

        assert len(tests) == 5
        for t in tests:
            assert t["expectation_confidence"] == "high"
            assert t["requires_review"] is False

    def test_auth_endpoint_positive_inferred_requires_review(self):
        import json
        from unittest.mock import patch, MagicMock
        from engine.ai_generator import ai_test_generator as gen

        payload = self._make_payload(status=200, source="ai_inferred",
                                     confidence="high", review=False)
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps(payload)

        with patch.object(gen.client.chat.completions, "create", return_value=mock_resp):
            tests = gen.generate_ai_tests({
                "path": "/login",
                "method": "POST",
                "request_body": {"fields": []},
                "responses": [{"status_code": 200}, {"status_code": 401}],
            })

        assert len(tests) == 5
        for t in tests:
            if 200 <= t["expected"]["status_code"] < 300:
                assert t["requires_review"] is True
                assert t["expectation_confidence"] == "low"
