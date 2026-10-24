import os
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from engine.test_generator.rule_based_generator import (
    get_expected_success_status
)
# Load .env from agent_backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")

# Gemini client
client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=60.0,
    max_retries=0
)

GEMINI_MODEL = "gemini-3.5-flash-lite"


# ---------------------------------------------------------------------------
# Constants for expectation provenance tracking
# ---------------------------------------------------------------------------

EXPECTED_SOURCE_OPENAPI = "openapi_spec"          # Derived from documented response codes
EXPECTED_SOURCE_INFERRED = "ai_inferred"           # AI reasoning, no OpenAPI-documented basis
EXPECTED_SOURCE_FIXTURE = "configured_fixture"     # From explicit test fixture / config

# Confidence thresholds used during validation
_HIGH_CONFIDENCE = "high"
_LOW_CONFIDENCE = "low"

# Security-related keywords that signal an authentication / authorisation endpoint.
# This list is intentionally generic — no hardcoded paths or business domains.
_AUTH_KEYWORDS = {
    "login", "logout", "signin", "signout",
    "authenticate", "token", "auth", "password",
    "credential", "session",
}


def _is_auth_endpoint(api_info):
    """Return True when the endpoint is likely an authentication endpoint."""
    path_lower = api_info.get("path", "").lower()
    method_lower = api_info.get("method", "").lower()
    # Auth endpoints are almost exclusively POST
    if method_lower not in ("post", "put", "patch"):
        return False
    return any(kw in path_lower for kw in _AUTH_KEYWORDS)


def _documented_status_codes(api_info):
    """Return the set of integer HTTP status codes from the OpenAPI responses list."""
    codes = set()
    for resp in api_info.get("responses", []):
        raw = resp.get("status_code")
        try:
            codes.add(int(raw))
        except (TypeError, ValueError):
            pass
    return codes


def _payload_violates_documented_schema(payload, api_info):
    """
    Check whether a request payload violates any documented schema constraints.
    Returns (True, reason) if a constraint is violated, or (False, None) if the
    payload satisfies all documented constraints.
    """
    if not isinstance(payload, dict):
        return False, None

    request_body = api_info.get("request_body") or {}
    fields = request_body.get("fields")
    if fields is None and "properties" in request_body:
        properties = request_body.get("properties", {})
        required = set(request_body.get("required", []))
        fields = []
        for pname, pdata in properties.items():
            fdict = {
                "name": pname,
                "type": pdata.get("type"),
                "format": pdata.get("format"),
                "required": pname in required,
                "nullable": pdata.get("nullable", False),
            }
            for c in ("minimum", "maximum", "minLength", "maxLength", "pattern", "enum"):
                if c in pdata:
                    fdict[c] = pdata[c]
            fields.append(fdict)

    if not fields:
        return False, None

    for field in fields:
        name = field.get("name")
        if not name:
            continue

        # 1. Missing required field
        if field.get("required") and name not in payload:
            return True, f"Required field '{name}' is missing"

        if name not in payload:
            continue

        val = payload[name]

        # Nullable check
        if val is None:
            if not field.get("nullable", False):
                return True, f"Field '{name}' is null but not nullable"
            continue

        # 2. Type checks
        ftype = field.get("type")
        if ftype == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                return True, f"Field '{name}' expects integer, got {type(val).__name__}"
        elif ftype == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                return True, f"Field '{name}' expects number, got {type(val).__name__}"
        elif ftype == "string":
            if not isinstance(val, str):
                return True, f"Field '{name}' expects string, got {type(val).__name__}"
        elif ftype == "boolean":
            if not isinstance(val, bool):
                return True, f"Field '{name}' expects boolean, got {type(val).__name__}"
        elif ftype == "array":
            if not isinstance(val, list):
                return True, f"Field '{name}' expects array, got {type(val).__name__}"

        # 3. Numeric constraints
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            min_val = field.get("minimum")
            max_val = field.get("maximum")
            if min_val is not None and val < min_val:
                return True, f"Field '{name}' value {val} < minimum {min_val}"
            if max_val is not None and val > max_val:
                return True, f"Field '{name}' value {val} > maximum {max_val}"

        # 4. String constraints
        if isinstance(val, str):
            min_len = field.get("minLength")
            max_len = field.get("maxLength")
            if min_len is not None and len(val) < min_len:
                return True, f"Field '{name}' length {len(val)} < minLength {min_len}"
            if max_len is not None and len(val) > max_len:
                return True, f"Field '{name}' length {len(val)} > maxLength {max_len}"

            pattern = field.get("pattern")
            if pattern:
                import re
                try:
                    if not re.search(pattern, val):
                        return True, f"Field '{name}' does not match pattern {pattern}"
                except re.error:
                    pass

            # Format constraint (email)
            fmt = field.get("format")
            if fmt == "email":
                try:
                    from email_validator import validate_email, EmailNotValidError
                    validate_email(str(val), check_deliverability=False)
                except ImportError:
                    import re
                    email_re = r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$"
                    if not re.match(email_re, str(val)):
                        return True, f"Field '{name}' value {val!r} violates email format"
                except Exception as eve:
                    return True, f"Field '{name}' value {val!r} violates email format: {eve}"

        # 5. Enum constraint
        enum_vals = field.get("enum")
        if enum_vals is not None and val not in enum_vals:
            return True, f"Field '{name}' value {val!r} not in enum {enum_vals}"

    return False, None


_DEBUG_DIAGNOSTICS = os.getenv("DEBUG_DIAGNOSTICS", "false").lower() in ("true", "1", "yes")


def _debug_log(*args, **kwargs):
    if _DEBUG_DIAGNOSTICS:
        print("[DIAGNOSTIC]", *args, **kwargs)


def generate_ai_tests(api_info):
    """
    Generate AI-powered edge-case tests for one endpoint.

    Each returned test carries:
      - expected.status_code   : the anticipated HTTP status
      - expected_source        : where the expectation came from
      - expectation_confidence : 'high' or 'low'
      - requires_review        : True when the expectation is uncertain
      - review_reason          : explanation when requires_review is True
    """
    success_status = get_expected_success_status(api_info)
    documented_codes = _documented_status_codes(api_info)
    is_auth = _is_auth_endpoint(api_info)

    # Diagnostic log: documented_codes for each endpoint
    _debug_log(
        f"Endpoint: {api_info.get('method')} {api_info.get('path')} | "
        f"documented_codes: {sorted(documented_codes)}"
    )

    # Build a concise summary of documented responses to ground the AI.
    documented_responses_text = (
        ", ".join(str(c) for c in sorted(documented_codes))
        if documented_codes
        else "not explicitly listed"
    )

    auth_guidance = ""
    if is_auth:
        auth_guidance = (
            "\nThis endpoint appears to be an authentication endpoint.\n"
            "Rules specific to authentication endpoints:\n"
            "- Do NOT generate positive tests that expect a successful login "
            "unless valid credentials are provided via a configured test fixture.\n"
            "- When testing edge cases (unusual emails, passwords with whitespace, "
            "unicode, long or short strings), these are schema-valid credentials.\n"
            "- The server validates credentials against the user database, "
            "returning HTTP 401 (or 403), NOT HTTP 422 schema validation errors.\n"
            "- Invalid or unknown credentials must expect HTTP 401, NOT 422.\n"
            "- Use synthetic non-existent credentials on valid domains (e.g. unknown.edge.user@example.com) "
            "for credential tests.\n"
        )

    prompt = f"""
You are an expert API tester generating edge-case tests.

Generate exactly 5 additional intelligent test cases.

Endpoint: {api_info["path"]}
Method: {api_info["method"]}
Documented HTTP response codes: {documented_responses_text}

Request body schema:
{json.dumps(api_info.get("request_body"), indent=2)}
{auth_guidance}
Focus areas for edge cases:
1. Boundary values for numeric or length-constrained fields
2. Unusual but schema-valid inputs that exercise non-obvious code paths
3. Very large or very small values within documented constraints
4. Special characters in string fields (kept schema-valid)
5. Interesting combinations of valid inputs

Do NOT generate:
- Tests for missing required fields (already covered by rule-based generator)
- Tests for basic wrong data types (already covered)
- Tests for null values on non-nullable fields (already covered)

Decision rules for expected_status and confidence:
1. Schema-validation errors (HTTP 422):
   - Expect HTTP 422 ONLY when the test payload intentionally violates an explicit documented schema constraint:
     * A numeric value outside minimum or maximum
     * A string violating documented minLength, maxLength, or regex pattern
     * A value violating an enum or wrong data type
     * A malformed value violating format constraints (e.g. invalid email format)
   - Do NOT expect HTTP 422 for unusual emails, short passwords, whitespace, or Unicode unless an explicit constraint (minLength, pattern, etc.) is documented in the schema. Unconstrained strings are schema-valid.
2. Authentication / Authorization endpoints:
   - When generating edge cases with synthetic/unknown credentials, the expected response is HTTP 401 (Unauthorized) or 403 (Forbidden), NEVER HTTP 422.
   - A short, long, whitespace, or Unicode password is schema-valid and is evaluated by the authentication service, resulting in 401, NOT 422.
   - If 401 is explicitly documented in the responses, use status_code=401, source="openapi_spec", confidence="high", requires_review=false.
   - If 401 is NOT documented in the responses, use status_code=401, source="ai_inferred", confidence="low", requires_review=true (review_reason="HTTP 401 is standard for authentication failure but not explicitly declared in the OpenAPI specification").
   - Use synthetic, non-existent test accounts on valid domains (e.g. unknown.edge.user@example.com) for invalid credential tests.
3. General Schema-Valid Inputs:
   - For non-auth endpoints, schema-valid inputs expect the success status code ({success_status}), source="openapi_spec", confidence="high", requires_review=false.
4. When uncertain:
   - If an outcome cannot be determined from the contract with confidence, set source="ai_inferred", confidence="low", requires_review=true with an explanatory review_reason.
5. Never set status_code to a boolean. Always use a plain integer.

Return ONLY valid JSON matching this exact format:
{{
  "tests": [
    {{
      "category": "boundary",
      "description": "Brief description of the scenario",
      "request": {{
        "body": {{}}
      }},
      "expected": {{
        "status_code": {success_status}
      }},
      "expected_source": "openapi_spec",
      "expectation_confidence": "high",
      "requires_review": false,
      "review_reason": null
    }}
  ]
}}

The example status_code above is illustrative only; choose the appropriate
code for each test based on the decision rules. The tests array must contain exactly 5 items.
Do not include markdown, explanations, or any text outside the JSON object.
"""

    for attempt in range(1, 4):
        print(f"[AI Generator] Attempt {attempt}/3")

        try:
            print(
                f"[AI Generator] Calling Gemini API "
                f"(model: {GEMINI_MODEL})..."
            )

            response = client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=4000,
                response_format={"type": "json_object"}
            )

            message = response.choices[0].message
            response_text = (message.content or "").strip()

            if not response_text:
                raise ValueError("Empty response from AI API")

            # Parse the first complete JSON object.
            start = response_text.find("{")

            if start == -1:
                raise ValueError("No JSON object found in AI response")

            data, _ = json.JSONDecoder().raw_decode(
                response_text[start:]
            )

            tests = data.get("tests")

            if not isinstance(tests, list) or len(tests) != 5:
                raise ValueError(
                    f"AI must return exactly 5 tests, got "
                    f"{len(tests) if isinstance(tests, list) else type(tests).__name__}"
                )

            ai_tests = []

            for test in tests:
                if not isinstance(test, dict):
                    raise ValueError("Each test must be a JSON object")

                if not all(
                    key in test
                    for key in ("category", "description", "request")
                ):
                    raise ValueError(
                        f"AI test missing required fields; got keys: "
                        f"{list(test.keys())}"
                    )

                request = test["request"]

                if not isinstance(request, dict):
                    raise ValueError("Test request must be a JSON object")

                if "body" not in request:
                    raise ValueError(
                        "AI test request must include a body key"
                    )

                if not isinstance(request["body"], dict):
                    raise ValueError(
                        "AI test request body must be a JSON object"
                    )

                expected = test.get("expected")

                if not isinstance(expected, dict):
                    raise ValueError(
                        "AI test must include an expected object"
                    )

                # Diagnostic log: raw AI expected_status_code
                raw_status_code = expected.get("status_code")
                _debug_log(f"raw AI expected_status_code: {raw_status_code}")

                status_code = raw_status_code

                if (
                    not isinstance(status_code, int)
                    or isinstance(status_code, bool)
                    or not 100 <= status_code <= 599
                ):
                    raise ValueError(
                        f"expected.status_code must be a valid HTTP status "
                        f"integer, got {status_code!r}"
                    )

                # Diagnostic log: expected_status_code after parsing
                _debug_log(f"expected_status_code after parsing: {status_code}")

                # --------------- Provenance / confidence ---------------
                raw_source = test.get("expected_source", "")
                raw_confidence = test.get("expectation_confidence", "")
                raw_requires_review = test.get("requires_review")
                raw_review_reason = test.get("review_reason")

                # Normalise source
                if raw_source not in (
                    EXPECTED_SOURCE_OPENAPI,
                    EXPECTED_SOURCE_INFERRED,
                    EXPECTED_SOURCE_FIXTURE,
                ):
                    raw_source = EXPECTED_SOURCE_INFERRED

                # Normalise confidence
                if raw_confidence not in (_HIGH_CONFIDENCE, _LOW_CONFIDENCE):
                    raw_confidence = _LOW_CONFIDENCE

                # Normalise requires_review to bool
                if isinstance(raw_requires_review, bool):
                    requires_review = raw_requires_review
                elif isinstance(raw_requires_review, str):
                    requires_review = raw_requires_review.lower() in (
                        "true", "1", "yes"
                    )
                else:
                    requires_review = False

                # Normalise review_reason to str or None
                if isinstance(raw_review_reason, str) and raw_review_reason.strip():
                    review_reason = raw_review_reason.strip()
                else:
                    review_reason = None

                # Check whether request payload violates documented schema constraints
                payload = request.get("body", {})
                violates_schema, schema_violation_reason = _payload_violates_documented_schema(
                    payload, api_info
                )

                # ── Deterministic enforcement gate ──────────────────────────
                # 1. Schema-valid inputs expecting 422:
                # HTTP 422 is ONLY for schema-validation errors. If the payload does
                # not violate any documented schema constraint, expecting 422 is an
                # ungrounded expectation that must be corrected.
                if status_code == 422 and not violates_schema:
                    if is_auth:
                        # On authentication endpoints, schema-valid credentials test
                        # authentication, not schema validation.
                        status_code = 401
                        if 401 in documented_codes:
                            raw_source = EXPECTED_SOURCE_OPENAPI
                            raw_confidence = _HIGH_CONFIDENCE
                            requires_review = False
                            review_reason = None
                        else:
                            raw_source = EXPECTED_SOURCE_INFERRED
                            raw_confidence = _LOW_CONFIDENCE
                            requires_review = True
                            review_reason = (
                                "Authentication endpoints return 401 for invalid credentials; "
                                "input is schema-valid so 422 is not expected. "
                                "HTTP 401 is inferred as it is not explicitly listed in OpenAPI responses."
                            )
                    else:
                        # On non-auth endpoints, schema-valid inputs are expected to succeed.
                        status_code = success_status
                        raw_source = (
                            EXPECTED_SOURCE_OPENAPI
                            if success_status in documented_codes
                            else EXPECTED_SOURCE_INFERRED
                        )
                        raw_confidence = (
                            _HIGH_CONFIDENCE
                            if success_status in documented_codes
                            else _LOW_CONFIDENCE
                        )
                        requires_review = success_status not in documented_codes
                        if requires_review:
                            review_reason = (
                                f"Input is schema-valid. Expected success status {success_status} "
                                f"is not in documented responses."
                            )
                        else:
                            review_reason = None

                # 2. Authentication endpoints expecting 401:
                elif is_auth and status_code == 401:
                    if 401 in documented_codes:
                        raw_source = EXPECTED_SOURCE_OPENAPI
                        raw_confidence = _HIGH_CONFIDENCE
                        requires_review = False
                    else:
                        raw_source = EXPECTED_SOURCE_INFERRED
                        raw_confidence = _LOW_CONFIDENCE
                        requires_review = True
                        if not review_reason:
                            review_reason = (
                                "HTTP 401 is standard for authentication failure but not "
                                "explicitly listed in OpenAPI responses."
                            )

                # 3. Status code not in documented codes:
                if documented_codes and status_code not in documented_codes:
                    raw_source = EXPECTED_SOURCE_INFERRED
                    raw_confidence = _LOW_CONFIDENCE
                    requires_review = True
                    if not review_reason:
                        review_reason = (
                            f"Status code {status_code} is not in the "
                            f"documented responses "
                            f"({', '.join(str(c) for c in sorted(documented_codes))}). "
                            f"Expected outcome cannot be confirmed from the contract."
                        )

                # 4. Security rule: force auth endpoints with positive expectation
                # without configured valid credentials to require review.
                if is_auth and 200 <= status_code < 300:
                    if raw_source != EXPECTED_SOURCE_FIXTURE:
                        requires_review = True
                        raw_confidence = _LOW_CONFIDENCE
                        if not review_reason:
                            review_reason = (
                                "Authentication success cannot be asserted without "
                                "configured valid credentials."
                            )

                # Diagnostic log: fields after enforcement gate
                _debug_log(
                    f"after enforcement gate: expected_status_code={status_code}, "
                    f"expected_source={raw_source}, expectation_confidence={raw_confidence}, "
                    f"requires_review={requires_review}"
                )

                # Low-confidence or review-required tests are tagged so
                # downstream consumers can handle them gracefully.
                ai_tests.append({
                    "endpoint": api_info["path"],
                    "method": api_info["method"],
                    "category": test["category"],
                    "description": test["description"],
                    "request": request,
                    "expected": {
                        "status_code": status_code
                    },
                    "expected_source": raw_source,
                    "expectation_confidence": raw_confidence,
                    "requires_review": requires_review,
                    "review_reason": review_reason,
                })

            print(
                f"[AI Generator] Successfully generated "
                f"{len(ai_tests)} AI tests."
            )

            return ai_tests

        except Exception as e:
            print(
                f"[AI Generator] Attempt {attempt}/3 failed: {e}"
            )

            if attempt < 3:
                print("[AI Generator] Retrying...")
            else:
                print("[AI Generator] All 3 attempts failed.")

    return []