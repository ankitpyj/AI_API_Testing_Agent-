"""
Regression tests for:
  - response_validator.validate_schema()
  - response_validator.validate_response()
  - rule_based_generator helpers
  - DELETE-last sort behaviour

No network calls. No LLM calls. No database calls.
Run with: python -m pytest tests/ -v
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from test_generator.response_validator import validate_schema, validate_response
from test_generator.rule_based_generator import (
    generate_valid_value,
    generate_wrong_type,
    generate_tests_for_endpoint,
    generate_valid_path_value,
    get_expected_validation_error_status,
)
from test_generator.test_executor import sort_tests_for_execution
from parser.openapi_parser import resolve_schema, extract_schema_details


# ─────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────

USER_SCHEMA = {
    "type": "object",
    "properties": {
        "id":    {"type": "integer"},
        "name":  {"type": "string"},
        "email": {"type": "string"},
        "age":   {"type": "integer"},
    },
    "required": ["id", "name", "email", "age"],
}

HEALTH_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok"]},
    },
    "required": ["status"],
}

MINIMAL_ENDPOINT_NO_BODY = {
    "method": "GET",
    "path": "/users",
    "parameters": [],
    "request_body": None,
    "responses": [{"status_code": "200", "content": {}}],
}

POST_ENDPOINT = {
    "method": "POST",
    "path": "/users",
    "parameters": [],
    "request_body": {
        "content_type": "application/json",
        "required": True,
        "fields": [
            {"name": "name",  "type": "string",  "format": None,    "required": True,  "nullable": False},
            {"name": "email", "type": "string",  "format": "email", "required": True,  "nullable": False},
            {"name": "age",   "type": "integer", "format": None,    "required": True,  "nullable": False},
        ],
    },
    "responses": [{"status_code": "201", "content": {}}],
}

DELETE_ENDPOINT = {
    "method": "DELETE",
    "path": "/users/{user_id}",
    "parameters": [{"name": "user_id", "location": "path", "type": "integer", "required": True}],
    "request_body": None,
    "responses": [{"status_code": "200", "content": {}}],
}

MINIMAL_OPENAPI = {"components": {"schemas": {}}}


# ─────────────────────────────────────────────────────────────────
# Group A — validate_schema() unit tests
# ─────────────────────────────────────────────────────────────────

class TestValidateSchema(unittest.TestCase):

    def test_A1_valid_user_response(self):
        """A1: A fully valid user dict passes the user schema."""
        data = {"id": 1, "name": "Ankit", "email": "a@b.com", "age": 21}
        self.assertTrue(validate_schema(data, USER_SCHEMA))

    def test_A2_health_ok_passes(self):
        """A2: status='ok' passes when enum is ['ok']."""
        data = {"status": "ok"}
        self.assertTrue(validate_schema(data, HEALTH_SCHEMA))

    def test_A3_health_error_fails(self):
        """A3 — API DEFECT: status='error' must fail when enum is ['ok'].
        This detects the planted health endpoint bug."""
        data = {"status": "error"}
        self.assertFalse(validate_schema(data, HEALTH_SCHEMA))

    def test_A4_wrong_type_string_for_integer(self):
        """A4 — API DEFECT: 'age' must be an integer, not a string."""
        data = {"id": 1, "name": "X", "email": "x@x.com", "age": "twenty-one"}
        self.assertFalse(validate_schema(data, USER_SCHEMA))

    def test_A5_missing_required_field(self):
        """A5 — API DEFECT: 'name' is required but absent."""
        data = {"id": 1, "email": "x@x.com", "age": 21}
        self.assertFalse(validate_schema(data, USER_SCHEMA))

    def test_A6_body_is_a_list(self):
        """A6 — API DEFECT: body is a list, not a dict."""
        self.assertFalse(validate_schema([1, 2, 3], USER_SCHEMA))

    def test_A7_bool_rejected_as_integer(self):
        """A7 — API DEFECT: True is a bool subclass of int; must be rejected."""
        data = {"id": 1, "name": "X", "email": "x@x.com", "age": True}
        self.assertFalse(validate_schema(data, USER_SCHEMA))

    def test_A8_no_example_any_string_passes(self):
        """A8: When schema has no example, any valid string value passes."""
        schema = {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        }
        self.assertTrue(validate_schema({"msg": "anything at all"}, schema))

    def test_A9_dict_rejected_when_array_expected(self):
        """A9 — API DEFECT: A dictionary must not pass validation when array is expected."""
        schema = {"type": "array"}
        self.assertFalse(validate_schema({"whatever": 1}, schema))


# ─────────────────────────────────────────────────────────────────
# Group B — validate_response() pipeline tests
# ─────────────────────────────────────────────────────────────────

def _make_result(expected_status, actual_status, body, schema=None):
    """Helper to build a result dict for validate_response()."""
    return {
        "test_id": "TC-TEST",
        "endpoint": "/test",
        "method": "GET",
        "request": {},
        "expected": {
            "status_code": expected_status,
            "response_schema": schema,
        },
        "actual": {
            "status_code": actual_status,
            "body": body,
        },
    }


class TestValidateResponse(unittest.TestCase):

    def test_B1_pass_status_and_valid_body(self):
        """B1: Status matches and body is valid → overall PASS."""
        result = _make_result(200, 200, {"id": 1, "name": "X", "email": "e@e.com", "age": 21}, USER_SCHEMA)
        out = validate_response(result)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["status_check"], "PASS")
        self.assertEqual(out["body_check"], "PASS")

    def test_B2_api_defect_health_body_wrong_value(self):
        """B2 — API DEFECT: HTTP 200 passes but body says 'error' → FAIL.
        This is the planted health endpoint bug scenario."""
        result = _make_result(200, 200, {"status": "error"}, HEALTH_SCHEMA)
        out = validate_response(result)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["status_check"], "PASS")
        self.assertEqual(out["body_check"], "FAIL")
        self.assertIn("body", out["failure_reason"].lower())

    def test_B3_api_defect_wrong_status_code(self):
        """B3 — API DEFECT: expected 200 but received 404 → FAIL, body SKIP."""
        result = _make_result(200, 404, {"detail": "Not found"}, USER_SCHEMA)
        out = validate_response(result)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["status_check"], "FAIL")
        self.assertEqual(out["body_check"], "SKIP")

    def test_B4_pass_status_no_schema(self):
        """B4: Status matches, no schema defined → PASS with body SKIP."""
        result = _make_result(200, 200, {"anything": "goes"}, schema=None)
        out = validate_response(result)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["body_check"], "SKIP")

    def test_B5_negative_test_422_body_skipped(self):
        """B5: Expected status is 422 (error response) → body check SKIP.
        Schema should not be validated for intentional error responses."""
        error_schema = {"type": "object", "properties": {"detail": {"type": "string"}}}
        result = _make_result(422, 422, {"detail": "Validation error"}, error_schema)
        out = validate_response(result)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["body_check"], "SKIP")

    def test_B6_infrastructure_failure_none_status(self):
        """B6 — INFRASTRUCTURE: network failure gives status None → FAIL."""
        result = _make_result(200, None, None, USER_SCHEMA)
        out = validate_response(result)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["status_check"], "FAIL")


# ─────────────────────────────────────────────────────────────────
# Group C — Rule-based generator helpers (no network)
# ─────────────────────────────────────────────────────────────────

class TestRuleBasedGeneratorHelpers(unittest.TestCase):

    def test_C1_valid_value_string(self):
        """C1: Valid value for string field is a str."""
        result = generate_valid_value({"type": "string"})
        self.assertIsInstance(result, str)

    def test_C2_valid_value_integer(self):
        """C2: Valid value for integer field is an int."""
        result = generate_valid_value({"type": "integer"})
        self.assertIsInstance(result, int)

    def test_C3_valid_value_email(self):
        """C3: Valid value for email field contains '@'."""
        result = generate_valid_value({"type": "string", "format": "email"})
        self.assertIn("@", result)

    def test_C4_wrong_type_integer_returns_string(self):
        """C4: Wrong-type value for integer field must be a non-integer."""
        result = generate_wrong_type({"type": "integer"})
        self.assertNotIsInstance(result, int)

    def test_C5_endpoint_no_body_generates_one_positive_test(self):
        """C5: GET endpoint with no body → exactly 1 test, positive category."""
        tests = generate_tests_for_endpoint(MINIMAL_ENDPOINT_NO_BODY, MINIMAL_OPENAPI)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0]["category"], "positive")

    def test_C6_post_endpoint_generates_positive_and_negative_tests(self):
        """C6: POST endpoint with 3 required fields → positive test and negatives."""
        tests = generate_tests_for_endpoint(POST_ENDPOINT, MINIMAL_OPENAPI)
        categories = [t["category"] for t in tests]
        self.assertIn("positive", categories)
        self.assertIn("negative", categories)
        # Must have more than 1 test
        self.assertGreater(len(tests), 1)

    def test_C7_post_endpoint_missing_field_tests_count(self):
        """C7: 3 required fields → at least 3 missing-field tests."""
        tests = generate_tests_for_endpoint(POST_ENDPOINT, MINIMAL_OPENAPI)
        missing = [t for t in tests if "Missing required field" in t["description"]]
        self.assertGreaterEqual(len(missing), 3)

    def test_C8_negative_tests_expect_422(self):
        """C8: All negative tests from rule-based generator expect HTTP 422."""
        tests = generate_tests_for_endpoint(POST_ENDPOINT, MINIMAL_OPENAPI)
        for t in tests:
            if t["category"] == "negative":
                self.assertEqual(t["expected"]["status_code"], 422,
                    f"Negative test '{t['description']}' expected 422 but got "
                    f"{t['expected']['status_code']}")


# ─────────────────────────────────────────────────────────────────
# Group D — DELETE ordering
# ─────────────────────────────────────────────────────────────────

class TestDeleteOrdering(unittest.TestCase):

    def test_D1_delete_runs_last(self):
        """D1: After sort, the last test must be the DELETE test."""
        tests = [
            {"test_id": "TC-001", "method": "GET"},
            {"test_id": "TC-002", "method": "DELETE"},
            {"test_id": "TC-003", "method": "POST"},
            {"test_id": "TC-004", "method": "PUT"},
        ]
        sorted_tests = sort_tests_for_execution(tests)
        self.assertEqual(sorted_tests[-1]["method"], "DELETE")

    def test_D2_all_tests_preserved_after_sort(self):
        """D2: Sort must not drop any tests."""
        tests = [
            {"test_id": f"TC-{i:03}", "method": m}
            for i, m in enumerate(["GET", "DELETE", "POST", "PUT", "GET"], 1)
        ]
        sorted_tests = sort_tests_for_execution(tests)
        self.assertEqual(len(sorted_tests), 5)

    def test_D3_no_delete_tests_unchanged(self):
        """D3: If no DELETE tests, all tests are present and no crash."""
        tests = [
            {"test_id": "TC-001", "method": "GET"},
            {"test_id": "TC-002", "method": "POST"},
        ]
        sorted_tests = sort_tests_for_execution(tests)
        self.assertEqual(len(sorted_tests), 2)
        self.assertNotEqual(sorted_tests[-1]["method"], "DELETE")

    def test_D4_multiple_deletes_all_at_end(self):
        """D4: Multiple DELETE tests must all appear after all non-DELETE tests."""
        tests = [
            {"test_id": "TC-001", "method": "DELETE"},
            {"test_id": "TC-002", "method": "GET"},
            {"test_id": "TC-003", "method": "DELETE"},
            {"test_id": "TC-004", "method": "POST"},
        ]
        sorted_tests = sort_tests_for_execution(tests)
        methods = [t["method"] for t in sorted_tests]
        first_delete = next(i for i, m in enumerate(methods) if m == "DELETE")
        for m in methods[first_delete:]:
            self.assertEqual(m, "DELETE",
                "All DELETE tests must appear at the end with no non-DELETE after them.")


# ─────────────────────────────────────────────────────────────────
# Group E — Nested schemas, array validation, and recursive $ref resolution
# ─────────────────────────────────────────────────────────────────

class TestNestedSchemasAndRecursiveRefs(unittest.TestCase):

    def test_E1_valid_nested_object(self):
        """E1: Nested object with valid fields and types passes validation."""
        nested_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "profile": {
                    "type": "object",
                    "properties": {
                        "bio": {"type": "string"},
                        "score": {"type": "number"}
                    },
                    "required": ["bio", "score"]
                }
            },
            "required": ["id", "profile"]
        }
        data = {
            "id": 1,
            "profile": {
                "bio": "Developer",
                "score": 98.5
            }
        }
        self.assertTrue(validate_schema(data, nested_schema))

    def test_E2_missing_required_field_in_nested_object(self):
        """E2 — API DEFECT: Missing required 'bio' inside nested 'profile' object fails."""
        nested_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "profile": {
                    "type": "object",
                    "properties": {
                        "bio": {"type": "string"},
                        "score": {"type": "number"}
                    },
                    "required": ["bio", "score"]
                }
            },
            "required": ["id", "profile"]
        }
        data = {
            "id": 1,
            "profile": {
                "score": 98.5  # missing required 'bio'
            }
        }
        self.assertFalse(validate_schema(data, nested_schema))

    def test_E3_array_containing_invalid_item(self):
        """E3 — API DEFECT: An array item violating schema (string where int expected) fails."""
        array_schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "integer"}
                }
            },
            "required": ["tags"]
        }
        data = {"tags": [1, 2, "invalid-not-int", 4]}
        self.assertFalse(validate_schema(data, array_schema))

    def test_E4_valid_top_level_array_response(self):
        """E4: Top-level array response body validates items against schema."""
        top_level_array_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"}
                },
                "required": ["id", "name"]
            }
        }
        data = [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"}
        ]
        self.assertTrue(validate_schema(data, top_level_array_schema))

        # Confirm invalid item in top-level array fails
        invalid_data = [
            {"id": 1, "name": "Item 1"},
            {"id": 2}  # missing required 'name'
        ]
        self.assertFalse(validate_schema(invalid_data, top_level_array_schema))

    def test_E5_nested_ref_resolves_correctly(self):
        """E5: Nested $ref inside object properties and array items resolves recursively."""
        openapi_data = {
            "components": {
                "schemas": {
                    "Address": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"}
                        },
                        "required": ["city"]
                    },
                    "User": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "address": {"$ref": "#/components/schemas/Address"}
                        },
                        "required": ["name", "address"]
                    }
                }
            }
        }
        root_schema = {"$ref": "#/components/schemas/User"}
        resolved = resolve_schema(root_schema, openapi_data)

        self.assertEqual(resolved["type"], "object")
        address_schema = resolved["properties"]["address"]
        self.assertEqual(address_schema["type"], "object")
        self.assertEqual(address_schema["properties"]["city"]["type"], "string")

    def test_E6_recursive_cyclic_ref_does_not_loop(self):
        """E6: Cyclic/recursive $ref (e.g. self-referential Node) terminates without infinite loop."""
        openapi_data = {
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "integer"},
                            "next": {"$ref": "#/components/schemas/Node"}
                        },
                        "required": ["value"]
                    }
                }
            }
        }
        root_schema = {"$ref": "#/components/schemas/Node"}
        resolved = resolve_schema(root_schema, openapi_data)

        self.assertEqual(resolved["type"], "object")
        self.assertIn("value", resolved["properties"])
        self.assertIn("$ref", resolved["properties"]["next"])


# ─────────────────────────────────────────────────────────────────
# Group F — Correctness and Portability Audits
# ─────────────────────────────────────────────────────────────────

class TestCorrectnessAndPortability(unittest.TestCase):

    def test_F1_root_primitive_enum_validation(self):
        """F1: Enum and const constraints at root and property level are enforced."""
        enum_str_schema = {"type": "string", "enum": ["active", "inactive"]}
        self.assertTrue(validate_schema("active", enum_str_schema))
        self.assertTrue(validate_schema("inactive", enum_str_schema))
        self.assertFalse(validate_schema("pending", enum_str_schema))

        const_str_schema = {"type": "string", "const": "ok"}
        self.assertTrue(validate_schema("ok", const_str_schema))
        self.assertFalse(validate_schema("error", const_str_schema))

        enum_int_schema = {"type": "integer", "enum": [100, 200]}
        self.assertTrue(validate_schema(100, enum_int_schema))
        self.assertFalse(validate_schema(300, enum_int_schema))

    def test_F2_anyof_preserves_multiple_options(self):
        """F2: anyOf schemas with multiple non-null options are not reduced to first option."""
        multi_anyof = {
            "anyOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        }
        self.assertTrue(validate_schema("test", multi_anyof))
        self.assertTrue(validate_schema(42, multi_anyof))
        self.assertFalse(validate_schema(True, multi_anyof))
        self.assertFalse(validate_schema({"a": 1}, multi_anyof))

    def test_F3_oneof_validates_single_match(self):
        """F3: oneOf schemas require exactly one branch to match."""
        oneof_schema = {
            "oneOf": [
                {"type": "integer"},
                {"type": "number"}
            ]
        }
        # In python, integer matches both integer and number (2 options -> False)
        # A float matches number but not integer (1 option -> True)
        self.assertTrue(validate_schema(3.14, oneof_schema))

        disjoint_oneof = {
            "oneOf": [
                {"type": "string"},
                {"type": "boolean"}
            ]
        }
        self.assertTrue(validate_schema("valid", disjoint_oneof))
        self.assertTrue(validate_schema(False, disjoint_oneof))
        self.assertFalse(validate_schema(123, disjoint_oneof))

    def test_F4_rule_based_generator_respects_documented_400_status(self):
        """F4: Generator does not assume 422 when API documents 400 for client error."""
        endpoint_with_400 = {
            "method": "POST",
            "path": "/items",
            "parameters": [],
            "request_body": {
                "content_type": "application/json",
                "required": True,
                "fields": [
                    {"name": "sku", "type": "string", "format": None, "required": True, "nullable": False}
                ]
            },
            "responses": [
                {"status_code": "201", "content": {}},
                {"status_code": "400", "content": {}}
            ]
        }
        tests = generate_tests_for_endpoint(endpoint_with_400, MINIMAL_OPENAPI)
        negative_tests = [t for t in tests if t["category"] == "negative"]
        self.assertGreater(len(negative_tests), 0)
        for t in negative_tests:
            self.assertEqual(t["expected"]["status_code"], 400)

    def test_F5_path_params_without_user_id_hardcoding(self):
        """F5: Path parameters generate valid defaults dynamically without user_id assumption."""
        product_param = {"name": "product_id", "location": "path", "type": "integer", "example": 42}
        self.assertEqual(generate_valid_path_value(product_param), 42)

        uuid_param = {"name": "order_id", "location": "path", "type": "string", "format": "uuid"}
        val = generate_valid_path_value(uuid_param)
        self.assertIsInstance(val, str)
        self.assertIn("-", val)

        generic_slug = {"name": "slug", "location": "path", "type": "string"}
        val = generate_valid_path_value(generic_slug)
        self.assertEqual(val, "1")

    def test_F6_dict_fails_when_array_schema_expected(self):
        """F6: Dict fails validation against root array schema."""
        array_schema = {"type": "array", "items": {"type": "string"}}
        self.assertFalse(validate_schema({"key": "val"}, array_schema))
        self.assertTrue(validate_schema(["a", "b"], array_schema))


# ─────────────────────────────────────────────────────────────────
# Group G — Nullability and Optionality Handling
# ─────────────────────────────────────────────────────────────────

class TestNullabilityHandling(unittest.TestCase):

    def test_G1_extract_details_nullable_string_email_integer(self):
        """G1: extract_schema_details sets nullable=True and preserves non-null type/format for string, email, int."""
        schema = {
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Name"
                },
                "email": {
                    "anyOf": [{"type": "string", "format": "email"}, {"type": "null"}],
                    "title": "Email"
                },
                "age": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "title": "Age"
                }
            }
        }
        fields = extract_schema_details(schema, {})
        fields_by_name = {f["name"]: f for f in fields}

        # Nullable string
        self.assertTrue(fields_by_name["name"]["nullable"])
        self.assertEqual(fields_by_name["name"]["type"], "string")
        self.assertIsNone(fields_by_name["name"]["format"])
        self.assertFalse(fields_by_name["name"]["required"])

        # Nullable email
        self.assertTrue(fields_by_name["email"]["nullable"])
        self.assertEqual(fields_by_name["email"]["type"], "string")
        self.assertEqual(fields_by_name["email"]["format"], "email")
        self.assertFalse(fields_by_name["email"]["required"])

        # Nullable integer
        self.assertTrue(fields_by_name["age"]["nullable"])
        self.assertEqual(fields_by_name["age"]["type"], "integer")
        self.assertIsNone(fields_by_name["age"]["format"])
        self.assertFalse(fields_by_name["age"]["required"])

    def test_G2_extract_details_distinguishes_optional_from_nullable(self):
        """G2: An optional-but-non-nullable field has required=False and nullable=False."""
        schema = {
            "type": "object",
            "properties": {
                "required_non_nullable": {"type": "string"},
                "optional_non_nullable": {"type": "string", "default": "anon"},
                "required_nullable": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "optional_nullable": {"anyOf": [{"type": "integer"}, {"type": "null"}]}
            },
            "required": ["required_non_nullable", "required_nullable"]
        }
        fields = extract_schema_details(schema, {})
        by_name = {f["name"]: f for f in fields}

        # Required non-nullable
        self.assertTrue(by_name["required_non_nullable"]["required"])
        self.assertFalse(by_name["required_non_nullable"]["nullable"])

        # Optional non-nullable
        self.assertFalse(by_name["optional_non_nullable"]["required"])
        self.assertFalse(by_name["optional_non_nullable"]["nullable"])

        # Required nullable
        self.assertTrue(by_name["required_nullable"]["required"])
        self.assertTrue(by_name["required_nullable"]["nullable"])

        # Optional nullable
        self.assertFalse(by_name["optional_nullable"]["required"])
        self.assertTrue(by_name["optional_nullable"]["nullable"])

    def test_G3_rule_based_generator_skips_null_tests_for_nullable_fields(self):
        """G3: Generator does not produce negative null-value tests when schema explicitly permits null."""
        endpoint = {
            "method": "PUT",
            "path": "/users/{user_id}",
            "parameters": [{"name": "user_id", "location": "path", "type": "integer"}],
            "request_body": {
                "content_type": "application/json",
                "required": False,
                "fields": [
                    {"name": "name", "type": "string", "format": None, "required": False, "nullable": True},
                    {"name": "email", "type": "string", "format": "email", "required": False, "nullable": True},
                    {"name": "age", "type": "integer", "format": None, "required": False, "nullable": True}
                ]
            },
            "responses": [
                {"status_code": "200", "content": {}},
                {"status_code": "422", "content": {}}
            ]
        }
        tests = generate_tests_for_endpoint(endpoint, MINIMAL_OPENAPI)
        null_tests = [t for t in tests if "Null value for" in t["description"]]
        self.assertEqual(len(null_tests), 0, "No null-value tests should be generated for nullable fields.")

        # Confirm other negative tests (e.g. wrong type, invalid format) are still generated
        wrong_type_tests = [t for t in tests if "Wrong data type for" in t["description"]]
        self.assertEqual(len(wrong_type_tests), 3)
        invalid_format_tests = [t for t in tests if "Invalid email" in t["description"]]
        self.assertEqual(len(invalid_format_tests), 1)

    def test_G4_rule_based_generator_generates_null_test_for_optional_non_nullable(self):
        """G4: Optional non-nullable fields skip missing-field tests but still test null rejection."""
        endpoint = {
            "method": "PATCH",
            "path": "/profiles/{id}",
            "parameters": [{"name": "id", "location": "path", "type": "integer"}],
            "request_body": {
                "content_type": "application/json",
                "required": False,
                "fields": [
                    {"name": "nickname", "type": "string", "format": None, "required": False, "nullable": False}
                ]
            },
            "responses": [
                {"status_code": "200", "content": {}},
                {"status_code": "422", "content": {}}
            ]
        }
        tests = generate_tests_for_endpoint(endpoint, MINIMAL_OPENAPI)

        # Missing required field should NOT be generated (it is optional)
        missing_tests = [t for t in tests if "Missing required field" in t["description"]]
        self.assertEqual(len(missing_tests), 0)

        # Null value SHOULD be generated (it is non-nullable)
        null_tests = [t for t in tests if "Null value for nickname" in t["description"]]
        self.assertEqual(len(null_tests), 1)
        self.assertEqual(null_tests[0]["expected"]["status_code"], 422)

    def test_G5_oneof_preserves_nullable_information(self):
        """G5: oneOf with a null branch resolves to non-null type with nullable=True."""
        oneof_schema = {
            "oneOf": [
                {"type": "string", "format": "email"},
                {"type": "null"}
            ]
        }
        resolved = resolve_schema(oneof_schema, {})
        self.assertEqual(resolved["type"], "string")
        self.assertEqual(resolved["format"], "email")
        self.assertTrue(resolved["nullable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
