def validate_response(result):
    """
    Validate actual API status and, when appropriate,
    the response body against the expected schema.

    Distinguishes:
      - API contract violations    → failure_type="API_DEFECT"
      - Infrastructure failures    → failure_type="INFRASTRUCTURE_FAILURE"
      - Uncertain AI expectations  → failure_type="UNCERTAIN_EXPECTATION"
        (does NOT automatically become a confirmed bug report)

    Provenance fields used (all optional, backward-compatible):
      result["expectation_confidence"] : "high" | "low"
      result["requires_review"]        : bool
      result["expected_source"]        : "openapi_spec" | "ai_inferred" | ...
    """

    expected = result.get("expected", {})
    actual = result.get("actual", {})

    expected_status = expected.get("status_code")
    actual_status = actual.get("status_code")
    expected_schema = expected.get("response_schema")
    actual_body = actual.get("body")

    # Provenance / confidence metadata (absent for rule-based tests → defaults)
    expectation_confidence = result.get("expectation_confidence", "high")
    requires_review = result.get("requires_review", False)
    expected_source = result.get("expected_source", "openapi_spec")

    # Normalise booleans that might arrive as strings from older callers
    if isinstance(requires_review, str):
        requires_review = requires_review.lower() in ("true", "1", "yes")

    failure_reasons = []
    failure_type = None

    # ── 1. Infrastructure / network failures ─────────────────────────────
    if actual.get("error") is not None or actual_status is None:
        result["status"] = "FAIL"
        result["failure_type"] = "INFRASTRUCTURE_FAILURE"
        result["failure_reason"] = (
            f"Infrastructure/Network failure: "
            f"{actual.get('error') or 'No response received.'}"
        )
        result["status_check"] = "FAIL"
        result["body_check"] = "SKIP"
        result["expected_status"] = expected_status
        result["actual_status"] = actual_status
        result["expected_schema"] = expected_schema
        result["actual_body"] = actual_body
        return result

    # ── 2. Validate HTTP status ───────────────────────────────────────────
    if actual_status == expected_status:
        status_result = "PASS"
    else:
        status_result = "FAIL"

        if expectation_confidence == "low" or requires_review:
            # Mismatch on an uncertain AI expectation → not a confirmed defect
            failure_type = "UNCERTAIN_EXPECTATION"
            failure_reasons.append(
                f"Expected HTTP status {expected_status} (AI-inferred, "
                f"low confidence), but received {actual_status}. "
                f"This may indicate a test expectation error rather than "
                f"an API defect. Manual review recommended."
            )

        elif (
            isinstance(expected_status, int)
            and 200 <= expected_status < 300
            and actual_status in (404, 410)
            and result.get("request", {}).get("path_params")
        ):
            # Positive test hit a 404/410 and path parameters were present.
            # The most likely cause is that the resource does not exist in the
            # target API's database, NOT that the endpoint is broken.
            # Classify as RESOURCE_NOT_FOUND to prevent a false bug report.
            failure_type = "RESOURCE_NOT_FOUND"
            failure_reasons.append(
                f"Expected HTTP status {expected_status} but received "
                f"{actual_status}. The requested resource may not exist in "
                f"the target API's database. This is a test precondition "
                f"failure, NOT a confirmed API defect — no resource was "
                f"created before this test ran."
            )

        elif (
            isinstance(expected_status, int)
            and 400 <= expected_status < 500
            and isinstance(actual_status, int)
            and 400 <= actual_status < 500
            and actual_status != expected_status
        ):
            # Both expected and actual are client-error codes.
            # The test correctly predicted a client error but got a different
            # 4xx code (e.g., expected 422, got 400). Both mean the API
            # rejected the request. Classify as NEEDS_REVIEW, NOT API_DEFECT.
            failure_type = "NEEDS_REVIEW"
            failure_reasons.append(
                f"Expected HTTP status {expected_status} but received "
                f"{actual_status}. Both are client-error responses — the API "
                f"rejected the request as expected, but with a different status "
                f"code. The test expectation may be incorrect; manual review "
                f"recommended before classifying as a defect."
            )

        else:
            failure_type = "API_DEFECT"
            failure_reasons.append(
                f"Expected HTTP status {expected_status}, "
                f"but received {actual_status}."
            )

    # ── 3. Validate response schema (success responses only) ─────────────
    if expected_schema is None:
        body_result = "SKIP"

    elif (
        not isinstance(expected_status, int)
        or not 200 <= expected_status < 300
    ):
        # Error-response schema should not be checked against success schema.
        body_result = "SKIP"

    elif status_result == "FAIL":
        # Status mismatch — do not validate a success schema against
        # whatever the API actually returned.
        body_result = "SKIP"

    elif validate_schema(actual_body, expected_schema):
        body_result = "PASS"

    else:
        body_result = "FAIL"

        if expectation_confidence == "low" or requires_review:
            if failure_type is None:
                failure_type = "UNCERTAIN_EXPECTATION"
        else:
            if failure_type is None:
                failure_type = "API_DEFECT"

        failure_reasons.append(
            "Response body does not match the expected schema."
        )

    # ── 4. Determine overall result ───────────────────────────────────────
    overall_status = (
        "PASS"
        if status_result == "PASS" and body_result != "FAIL"
        else "FAIL"
    )

    # ── 5. Preserve result details ────────────────────────────────────────
    result["status"] = overall_status
    result["failure_type"] = failure_type if overall_status == "FAIL" else None
    result["failure_reason"] = (
        "; ".join(failure_reasons) if failure_reasons else None
    )
    result["status_check"] = status_result
    result["body_check"] = body_result

    result["expected_status"] = expected_status
    result["actual_status"] = actual_status
    result["expected_schema"] = expected_schema
    result["actual_body"] = actual_body

    return result



def validate_schema(data, schema, strict_examples=False):
    """
    Validate response data against a simplified OpenAPI schema.
    Keeps validation deterministic without LLM dependencies.
    Supports:
      - Objects with recursive validation of nested object properties
      - Arrays with element validation against items schema
      - Top-level array response bodies (rejects dictionaries)
      - Primitive data types with root and property enum constraints
      - anyOf and oneOf composition
      - Nullable fields
      - Non-strict illustrative examples
    """

    if not isinstance(schema, dict) or not schema:
        return True

    # -------------------------
    # Nullable handling
    # -------------------------
    if data is None:
        if schema.get("nullable") is True:
            return True
        if "anyOf" in schema and isinstance(schema["anyOf"], list):
            if any(isinstance(opt, dict) and opt.get("type") == "null" for opt in schema["anyOf"]):
                return True
        if "oneOf" in schema and isinstance(schema["oneOf"], list):
            if any(isinstance(opt, dict) and opt.get("type") == "null" for opt in schema["oneOf"]):
                return True
        return False

    # -------------------------
    # anyOf / oneOf composition
    # -------------------------
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        return any(
            validate_schema(data, opt, strict_examples=strict_examples)
            for opt in schema["anyOf"]
        )

    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        matches = [
            opt for opt in schema["oneOf"]
            if validate_schema(data, opt, strict_examples=strict_examples)
        ]
        return len(matches) == 1

    schema_type = schema.get("type")

    # -------------------------
    # Root / field enum / const constraint check
    # -------------------------
    if "const" in schema and data != schema["const"]:
        return False

    enum_values = schema.get("enum")
    if enum_values is not None and data not in enum_values:
        return False

    # -------------------------
    # Strict example check (disabled by default)
    # -------------------------
    example = schema.get("example")
    if example is not None and strict_examples:
        if data != example:
            return False

    # -------------------------
    # Top-level Array handling
    # -------------------------
    if schema_type == "array":
        if not isinstance(data, list):
            return False
        items_schema = schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            for item in data:
                if not validate_schema(item, items_schema, strict_examples=strict_examples):
                    return False
        return True

    # -------------------------
    # Primitive types handling
    # -------------------------
    if schema_type == "string":
        return isinstance(data, str)
    if schema_type == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if schema_type == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if schema_type == "boolean":
        return isinstance(data, bool)

    # -------------------------
    # Object handling
    # -------------------------
    if schema_type == "object":
        if not isinstance(data, dict):
            return False

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check required fields
        for field in required:
            if field not in data:
                return False

        # Validate each property recursively against its schema
        for field_name, field_schema in properties.items():
            if field_name not in data:
                continue
            if not validate_schema(data[field_name], field_schema, strict_examples=strict_examples):
                return False

        return True

    # If schema defines a custom/unrecognized type, skip without failing
    return True