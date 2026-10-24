"""
Unit tests for ai_test_generator.generate_ai_tests().

Covers:
  - Valid output generates exactly 5 tests with provenance fields
  - Malformed JSON retries then returns empty list
  - Wrong number of tests retried and rejected
  - Invalid status code types rejected (bool, string, out-of-range)
  - Missing required fields rejected
  - Uncertain expectations on auth endpoints trigger requires_review
  - Missing authentication fixtures: positive auth tests marked for review
  - API timeout retries three times
  - Unicode values in request bodies are preserved as-is
  - Backward compatibility: legacy callers without provenance fields

All LLM calls are mocked. No live API key required.
"""

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from engine.ai_generator import ai_test_generator as generator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

API_INFO = {
    "path": "/users",
    "method": "POST",
    "request_body": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "email": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "email", "age"],
    },
    "responses": [
        {"status_code": 201, "description": "User created successfully"},
        {"status_code": 422, "description": "Validation error"},
    ],
}

AUTH_API_INFO = {
    "path": "/login",
    "method": "POST",
    "request_body": {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email"},
            "password": {"type": "string"},
        },
        "required": ["email", "password"],
    },
    "responses": [
        {"status_code": 200, "description": "Login successful"},
        {"status_code": 401, "description": "Invalid credentials"},
    ],
}


def make_ai_response(content):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def make_valid_payload(status_code=201, include_provenance=False):
    """Build a minimal valid 5-test payload."""
    tests = []
    for i in range(5):
        test = {
            "category": "boundary",
            "description": f"Test case {i}",
            "request": {
                "body": {
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                    "age": i,
                }
            },
            "expected": {"status_code": status_code},
        }
        if include_provenance:
            test["expected_source"] = "openapi_spec"
            test["expectation_confidence"] = "high"
            test["requires_review"] = False
            test["review_reason"] = None
        tests.append(test)
    return {"tests": tests}


def make_auth_payload_with_positive_inferred():
    """
    Simulate an AI that returns a positive auth test with inferred source.
    The generator should automatically set requires_review=True.
    """
    tests = []
    for i in range(5):
        test = {
            "category": "boundary",
            "description": f"Auth test {i}",
            "request": {
                "body": {
                    "email": f"user{i}@example.com",
                    "password": "somepassword",
                }
            },
            "expected": {"status_code": 200},  # positive — but inferred
            "expected_source": "ai_inferred",
            "expectation_confidence": "high",
            "requires_review": False,
            "review_reason": None,
        }
        tests.append(test)
    return {"tests": tests}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch.object(generator.client.chat.completions, "create")
def test_valid_response_generates_exactly_five_tests(mock_create):
    """Valid AI output → exactly 5 tests with correct endpoint/method."""
    mock_create.return_value = make_ai_response(
        json.dumps(make_valid_payload(include_provenance=True))
    )

    tests = generator.generate_ai_tests(API_INFO)

    assert len(tests) == 5
    assert all(test["endpoint"] == "/users" for test in tests)
    assert all(test["method"] == "POST" for test in tests)
    assert all(test["expected"]["status_code"] == 201 for test in tests)
    mock_create.assert_called_once()


@patch.object(generator.client.chat.completions, "create")
def test_provenance_fields_present_on_every_test(mock_create):
    """Every returned test must carry all four provenance fields."""
    mock_create.return_value = make_ai_response(
        json.dumps(make_valid_payload(include_provenance=True))
    )

    tests = generator.generate_ai_tests(API_INFO)

    for t in tests:
        assert "expected_source" in t, "expected_source missing"
        assert "expectation_confidence" in t, "expectation_confidence missing"
        assert "requires_review" in t, "requires_review missing"
        assert "review_reason" in t, "review_reason missing"


@patch.object(generator.client.chat.completions, "create")
def test_invalid_json_retries_then_returns_empty_list(mock_create):
    """Malformed JSON → 3 retry attempts → empty list returned."""
    mock_create.return_value = make_ai_response("not valid JSON {{{{")

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_wrong_number_of_tests_is_rejected(mock_create):
    """AI returning fewer than 5 tests → rejected with retry → empty list."""
    payload = make_valid_payload()
    payload["tests"] = payload["tests"][:2]

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_too_many_tests_is_rejected(mock_create):
    """AI returning more than 5 tests → rejected."""
    payload = make_valid_payload()
    # Duplicate entries to get 7
    payload["tests"] = payload["tests"] + payload["tests"][:2]

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_bool_status_code_is_rejected(mock_create):
    """Boolean True must not be accepted as an integer status code."""
    payload = make_valid_payload()
    payload["tests"][0]["expected"]["status_code"] = True

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_string_status_code_is_rejected(mock_create):
    """String '201' must not be accepted as a valid status code."""
    payload = make_valid_payload()
    payload["tests"][2]["expected"]["status_code"] = "201"

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_out_of_range_status_code_is_rejected(mock_create):
    """Status code 99 (below 100) must be rejected."""
    payload = make_valid_payload()
    payload["tests"][1]["expected"]["status_code"] = 99

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_missing_description_field_is_rejected(mock_create):
    """A test object missing 'description' must be rejected."""
    payload = make_valid_payload()
    del payload["tests"][3]["description"]

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_missing_request_body_is_rejected(mock_create):
    """A test whose request has no 'body' key must be rejected."""
    payload = make_valid_payload()
    del payload["tests"][0]["request"]["body"]

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_api_timeout_retries_three_times(mock_create):
    """Network timeout → 3 retry attempts → empty list returned."""
    mock_create.side_effect = TimeoutError("Simulated timeout")

    tests = generator.generate_ai_tests(API_INFO)

    assert tests == []
    assert mock_create.call_count == 3


@patch.object(generator.client.chat.completions, "create")
def test_auth_endpoint_positive_inferred_requires_review(mock_create):
    """
    On an authentication endpoint, AI-inferred positive expectations must be
    automatically flagged as requires_review=True (no valid fixtures supplied).
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_auth_payload_with_positive_inferred())
    )

    tests = generator.generate_ai_tests(AUTH_API_INFO)

    assert len(tests) == 5
    for t in tests:
        if 200 <= t["expected"]["status_code"] < 300:
            assert t["requires_review"] is True, (
                f"Positive auth test '{t['description']}' should require review"
            )
            assert t["expectation_confidence"] == "low"
            assert t["review_reason"] is not None


@patch.object(generator.client.chat.completions, "create")
def test_auth_endpoint_negative_tests_not_flagged(mock_create):
    """
    Negative auth tests (status 401) must not be forced into requires_review.
    """
    negative_payload = {
        "tests": [
            {
                "category": "negative",
                "description": f"Invalid credentials test {i}",
                "request": {
                    "body": {
                        "email": f"bad{i}@x.com",
                        "password": "wrong",
                    }
                },
                "expected": {"status_code": 401},
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            }
            for i in range(5)
        ]
    }

    mock_create.return_value = make_ai_response(json.dumps(negative_payload))

    tests = generator.generate_ai_tests(AUTH_API_INFO)

    assert len(tests) == 5
    for t in tests:
        # 401 is documented — should NOT be downgraded
        assert t["expectation_confidence"] == "high"
        assert t["requires_review"] is False


@patch.object(generator.client.chat.completions, "create")
def test_unicode_body_preserved_in_generated_test(mock_create):
    """
    Unicode characters in request body fields must survive JSON round-trip
    unchanged inside the generator.
    """
    unicode_payload = {
        "tests": [
            {
                "category": "unicode",
                "description": "Unicode name field",
                "request": {
                    "body": {
                        "name": "Jos\u00e9 Garc\u00eda",
                        "email": "jose@example.com",
                        "age": 30,
                    }
                },
                "expected": {"status_code": 201},
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            }
        ]
        + [
            {
                "category": "boundary",
                "description": f"Filler test {i}",
                "request": {"body": {"name": "X", "email": f"x{i}@e.com", "age": i}},
                "expected": {"status_code": 201},
            }
            for i in range(4)
        ]
    }

    mock_create.return_value = make_ai_response(json.dumps(unicode_payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert len(tests) == 5
    unicode_test = next(t for t in tests if "unicode" in t["category"].lower())
    assert unicode_test["request"]["body"]["name"] == "Jos\u00e9 Garc\u00eda", (
        "Unicode characters must not be corrupted during generator processing"
    )


@patch.object(generator.client.chat.completions, "create")
def test_low_confidence_field_propagated(mock_create):
    """
    When AI returns expectation_confidence='low', the generator must preserve it.
    """
    payload = {
        "tests": [
            {
                "category": "boundary",
                "description": f"Uncertain test {i}",
                "request": {"body": {"name": "X", "email": f"x{i}@e.com", "age": i}},
                "expected": {"status_code": 201},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": "Cannot determine if this input succeeds",
            }
            for i in range(5)
        ]
    }

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert len(tests) == 5
    for t in tests:
        assert t["expectation_confidence"] == "low"
        assert t["requires_review"] is True
        assert t["review_reason"] is not None


@patch.object(generator.client.chat.completions, "create")
def test_invalid_expected_source_normalised_to_inferred(mock_create):
    """An unrecognised expected_source value must be normalised to 'ai_inferred'."""
    payload = make_valid_payload()
    for t in payload["tests"]:
        t["expected_source"] = "totally_unknown_source"

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert len(tests) == 5
    for t in tests:
        assert t["expected_source"] == "ai_inferred"


@patch.object(generator.client.chat.completions, "create")
def test_backward_compat_no_provenance_fields_still_accepted(mock_create):
    """
    AI output WITHOUT provenance fields (legacy format) must still produce
    5 valid tests.  Missing provenance fields get safe defaults.
    """
    payload = make_valid_payload(include_provenance=False)

    mock_create.return_value = make_ai_response(json.dumps(payload))

    tests = generator.generate_ai_tests(API_INFO)

    assert len(tests) == 5
    for t in tests:
        # Defaults should be applied
        assert "expected_source" in t
        assert "expectation_confidence" in t
        assert "requires_review" in t
        assert "review_reason" in t


# ---------------------------------------------------------------------------
# Enforcement gate: undocumented status code handling
# ---------------------------------------------------------------------------

# POST /login documents only 200 and 401.  No 422.
LOGIN_API_INFO = {
    "path": "/login",
    "method": "POST",
    "request_body": {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email"},
            "password": {"type": "string"},
        },
        "required": ["email", "password"],
    },
    "responses": [
        {"status_code": 200, "description": "Login successful"},
        {"status_code": 401, "description": "Invalid credentials"},
    ],
}


def make_login_payload_with_422():
    """
    Simulates the real failure: AI emits 422 for a short-password test on
    POST /login — but 422 is NOT in that endpoint's documented responses.
    """
    return {
        "tests": [
            {
                "category": "boundary",
                "description": "Short password (1 character)",
                "request": {"body": {"email": "test@example.com", "password": "x"}},
                "expected": {"status_code": 422},   # ← AI mistake: 422 not documented
                "expected_source": "openapi_spec",  # ← AI lie: it's not in the spec
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Very long email address",
                "request": {"body": {"email": "a" * 200 + "@example.com", "password": "pass"}},
                "expected": {"status_code": 200},   # ← AI mistake: no fixture supplied
                "expected_source": "ai_inferred",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            },
            {
                "category": "negative",
                "description": "Wrong password for valid email",
                "request": {"body": {"email": "test@example.com", "password": "wrongpass"}},
                "expected": {"status_code": 401},   # ← correct: 401 is documented
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Unicode password characters",
                "request": {"body": {"email": "u@example.com", "password": "\u00e9\u00e0\u00fc"}},
                "expected": {"status_code": 401},   # ← correct: treating as unknown creds
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Empty string password",
                "request": {"body": {"email": "e@example.com", "password": ""}},
                "expected": {"status_code": 401},   # ← reasonable; 401 is documented
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            },
        ]
    }


@patch.object(generator.client.chat.completions, "create")
def test_undocumented_422_on_login_downgraded_to_requires_review(mock_create):
    """
    On an authentication endpoint where 401 is documented, a schema-valid
    short-password test where AI mistakenly emitted 422 is corrected to 401.
    Because 401 is documented, it keeps high confidence and requires_review=False.
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_login_payload_with_422())
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO)

    assert len(tests) == 5

    short_pw_test = next(
        t for t in tests if "short password" in t["description"].lower()
    )

    # 422 is corrected to 401 because the input is schema-valid on an auth endpoint
    assert short_pw_test["expected"]["status_code"] == 401
    assert short_pw_test["expected_source"] == "openapi_spec"
    assert short_pw_test["expectation_confidence"] == "high"
    assert short_pw_test["requires_review"] is False


@patch.object(generator.client.chat.completions, "create")
def test_undocumented_200_on_login_auth_rule_also_applies(mock_create):
    """
    The long-email test with status 200 and source='ai_inferred' must be
    downgraded by BOTH the enforcement gate (200 is documented but source is
    inferred) AND the auth security rule (positive auth without fixture).
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_login_payload_with_422())
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO)

    long_email_test = next(
        t for t in tests if "long email" in t["description"].lower()
    )

    # 200 IS documented, but source is 'ai_inferred' + auth endpoint + 2xx -> auth rule triggers.
    assert long_email_test["requires_review"] is True
    assert long_email_test["expectation_confidence"] == "low"


@patch.object(generator.client.chat.completions, "create")
def test_documented_401_on_login_kept_at_high_confidence(mock_create):
    """
    Tests that correctly expect 401 (a documented code) are NOT downgraded.
    They should keep confidence='high' and requires_review=False.
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_login_payload_with_422())
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO)

    # The 3rd, 4th, and 5th tests all expect 401 with openapi_spec source.
    correct_401_tests = [
        t for t in tests
        if t["expected"]["status_code"] == 401
        and "openapi_spec" in t.get("expected_source", "")
    ]

    assert len(correct_401_tests) >= 1, (
        "At least one 401 test with openapi_spec source should remain"
    )
    for t in correct_401_tests:
        assert t["expectation_confidence"] == "high", (
            f"401 is documented for /login — should keep high confidence, "
            f"got {t['expectation_confidence']!r}"
        )
        assert t["requires_review"] is False


@patch.object(generator.client.chat.completions, "create")
def test_enforcement_gate_uses_correct_review_reason_message(mock_create):
    """
    When an unexpected status code that is NOT in documented_codes is returned
    and cannot be resolved from schema, review_reason must mention the actual code
    and the documented codes so it is useful for manual review.
    """
    undocumented_code_payload = {
        "tests": [
            {
                "category": "negative",
                "description": "Server error scenario",
                "request": {"body": {"email": "bad@example.com", "password": "x"}},
                "expected": {"status_code": 503},
                "expected_source": "ai_inferred",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            }
        ] + [
            {
                "category": "boundary",
                "description": f"Filler {i}",
                "request": {"body": {"email": f"u{i}@e.com", "password": "p"}},
                "expected": {"status_code": 401},
            }
            for i in range(4)
        ]
    }

    mock_create.return_value = make_ai_response(
        json.dumps(undocumented_code_payload)
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO)

    err_test = next(
        t for t in tests if "server error" in t["description"].lower()
    )

    reason = err_test["review_reason"]
    assert reason is not None
    assert "503" in reason
    assert "200" in reason or "401" in reason


# ===========================================================================
# Regression tests using EXACT live OpenAPI response-code structure
# In the live target API, POST /login documents ONLY 200 and 422.
# 401 is NOT documented in OpenAPI responses.
# ===========================================================================

LOGIN_API_INFO_LIVE = {
    "method": "POST",
    "path": "/login",
    "summary": "Login",
    "description": None,
    "parameters": [],
    "request_body": {
        "content_type": "application/json",
        "required": True,
        "fields": [
            {
                "name": "email",
                "type": "string",
                "format": "email",
                "required": True,
                "nullable": False,
            },
            {
                "name": "password",
                "type": "string",
                "format": None,
                "required": True,
                "nullable": False,
            },
        ],
    },
    "responses": [
        {
            "status_code": "200",
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginResponse"}
                }
            },
        },
        {
            "status_code": "422",
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/HTTPValidationError"
                    }
                }
            },
        },
    ],
}


def make_live_run_5_login_tests():
    """Exact 5 test cases observed in the live run (AI-TC-11 through AI-TC-15)."""
    return {
        "tests": [
            {
                "category": "boundary",
                "description": "Long password",
                "request": {
                    "body": {
                        "email": "test@example.com",
                        "password": "aVeryLongPasswordStringThatExceedsNormalExpectationsAndMeetsTheStringCriteria1234567890!@#$%^&*()",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Unicode characters in email",
                "request": {
                    "body": {
                        "email": "m\u00fcller@domain.com",
                        "password": "ValidPassword123",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Whitespace password",
                "request": {
                    "body": {
                        "email": "user@example.com",
                        "password": "     ",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": None,
            },
            {
                "category": "boundary",
                "description": "Very long email address",
                "request": {
                    "body": {
                        "email": "very.common.and.long.but.completely.valid.email.address.string.with.lots.of.characters@very-long-domain-name-part-to-test-email-parsing-limits.com",
                        "password": "SecurePassword123!",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": None,
            },
            {
                "category": "negative",
                "description": "SQL injection string in email",
                "request": {
                    "body": {
                        "email": "admin'--@example.com",
                        "password": "SomePassword123",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": None,
            },
        ]
    }


@patch.object(generator.client.chat.completions, "create")
def test_live_login_spec_schema_valid_inputs_do_not_expect_422(mock_create):
    """
    On the EXACT live OpenAPI spec for POST /login (documented codes: 200, 422; 401 not documented):
    AI tests with schema-valid credentials (long password, unicode email, whitespace password)
    MUST NOT expect HTTP 422.
    They must be corrected to expect HTTP 401, with requires_review=True,
    expectation_confidence='low', and expected_source='ai_inferred'.
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_live_run_5_login_tests())
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO_LIVE)

    assert len(tests) == 5

    for t in tests:
        # None of the schema-valid credential tests may expect 422
        assert t["expected"]["status_code"] == 401, (
            f"Test '{t['description']}' should expect 401, got {t['expected']['status_code']}"
        )
        assert t["expected_source"] == "ai_inferred"
        assert t["expectation_confidence"] == "low"
        assert t["requires_review"] is True
        assert "401" in t["review_reason"]


@patch.object(generator.client.chat.completions, "create")
def test_live_login_spec_schema_violating_input_preserves_422(mock_create):
    """
    On the live OpenAPI spec for POST /login, when an input ACTUALLY violates
    a documented schema constraint (e.g. malformed email format),
    HTTP 422 IS expected and preserved at high confidence because 422 is documented.
    """
    violating_payload = {
        "tests": [
            {
                "category": "negative",
                "description": "Malformed email format without at sign",
                "request": {
                    "body": {
                        "email": "notanemail",
                        "password": "ValidPassword123",
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            }
        ] + [
            {
                "category": "boundary",
                "description": f"Filler {i}",
                "request": {"body": {"email": f"u{i}@test.com", "password": "p"}},
                "expected": {"status_code": 401},
            }
            for i in range(4)
        ]
    }

    mock_create.return_value = make_ai_response(
        json.dumps(violating_payload)
    )

    tests = generator.generate_ai_tests(LOGIN_API_INFO_LIVE)

    malformed_test = next(
        t for t in tests if "malformed email" in t["description"].lower()
    )

    # 422 is valid because 'notanemail' violates format: email
    assert malformed_test["expected"]["status_code"] == 422
    assert malformed_test["expected_source"] == "openapi_spec"
    assert malformed_test["expectation_confidence"] == "high"
    assert malformed_test["requires_review"] is False


@patch.object(generator.client.chat.completions, "create")
def test_post_users_schema_valid_unicode_does_not_expect_422(mock_create):
    """
    On a non-auth endpoint (POST /users), if the AI mistakenly expects 422 for
    a schema-valid input (e.g. special characters in name), the gate corrects
    it to the success status code (201).
    """
    valid_payload_with_erroneous_422 = {
        "tests": [
            {
                "category": "boundary",
                "description": "Special characters in name",
                "request": {
                    "body": {
                        "name": "J\u00f6hn D'Arc-Smith",
                        "email": "john@example.com",
                        "age": 30,
                    }
                },
                "expected": {"status_code": 422},
                "expected_source": "openapi_spec",
                "expectation_confidence": "high",
                "requires_review": False,
                "review_reason": None,
            }
        ] + [
            {
                "category": "boundary",
                "description": f"Filler {i}",
                "request": {"body": {"name": f"U{i}", "email": f"u{i}@e.com", "age": 20 + i}},
                "expected": {"status_code": 201},
            }
            for i in range(4)
        ]
    }

    mock_create.return_value = make_ai_response(
        json.dumps(valid_payload_with_erroneous_422)
    )

    tests = generator.generate_ai_tests(API_INFO)

    name_test = next(
        t for t in tests if "special characters" in t["description"].lower()
    )

    # Corrected to success status 201
    assert name_test["expected"]["status_code"] == 201
    assert name_test["expected_source"] == "openapi_spec"
    assert name_test["expectation_confidence"] == "high"
    assert name_test["requires_review"] is False


@patch.object(generator.client.chat.completions, "create")
def test_enforcement_gate_does_not_apply_when_no_documented_codes(mock_create):
    """
    When documented_codes is empty (no responses listed), the enforcement gate
    must NOT fire — we have no contract to enforce against.
    Tests should pass through with whatever provenance the AI supplied.
    """
    api_info_no_responses = {
        "path": "/mystery",
        "method": "POST",
        "request_body": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        "responses": [],   # no documented codes
    }

    # AI returns 999 — absurd, but enforcement gate should NOT trigger
    # because there are no documented codes to enforce against.
    # (The status code 999 is still rejected as out-of-range 100–599.)
    payload_with_valid_but_unusual = {
        "tests": [
            {
                "category": "boundary",
                "description": f"t{i}",
                "request": {"body": {"x": f"val{i}"}},
                "expected": {"status_code": 200},
                "expected_source": "ai_inferred",
                "expectation_confidence": "low",
                "requires_review": True,
                "review_reason": "No documented contract available",
            }
            for i in range(5)
        ]
    }

    mock_create.return_value = make_ai_response(
        json.dumps(payload_with_valid_but_unusual)
    )

    tests = generator.generate_ai_tests(api_info_no_responses)

    assert len(tests) == 5
    # All should have the AI's own provenance untouched
    for t in tests:
        assert t["expectation_confidence"] == "low"
        assert t["requires_review"] is True


@patch.object(generator.client.chat.completions, "create")
def test_enforcement_gate_with_post_users_does_not_downgrade_422(mock_create):
    """
    POST /users documents 422 — the enforcement gate must NOT downgrade a 422
    expectation on this endpoint. It is a valid documented code.
    """
    mock_create.return_value = make_ai_response(
        json.dumps(make_valid_payload(status_code=422, include_provenance=True))
    )

    tests = generator.generate_ai_tests(API_INFO)  # API_INFO has 422 documented

    assert len(tests) == 5
    for t in tests:
        if t["expected"]["status_code"] == 422:
            # 422 IS documented for /users — must NOT be downgraded
            assert t["requires_review"] is False, (
                "422 is documented for /users, must not be flagged for review"
            )
            assert t["expectation_confidence"] == "high"
