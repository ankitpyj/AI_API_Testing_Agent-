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
        result["expected_body"] = expected_schema
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

    # ── 3. Validate response schema ──────────────────────────────────────
    if expected_schema is None:
        body_result = "SKIP"

    elif status_result == "FAIL":
        # Status mismatch — do not validate a schema against
        # whatever unexpected response the API actually returned.
        body_result = "SKIP"

    else:
        violations = find_schema_violations(actual_body, expected_schema)
        if not violations:
            body_result = "PASS"
        else:
            body_result = "FAIL"

            if expectation_confidence == "low" or requires_review:
                if failure_type is None:
                    failure_type = "UNCERTAIN_EXPECTATION"
            else:
                if failure_type is None:
                    failure_type = "API_DEFECT"

            result["schema_violations"] = violations
            mismatch_detail = "; ".join(violations[:3])
            failure_reasons.append(
                f"Response body does not match the expected schema: {mismatch_detail}"
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
    # Provide expected_body as an alias so the frontend (which reads
    # expected_body from the DB column name) works for both live runs
    # and history-loaded runs.  None means "no schema defined in OpenAPI".
    result["expected_body"] = expected_schema
    result["actual_body"] = actual_body

    return result



def find_schema_violations(data, schema, strict_examples=False, path=""):
    """
    Validate response data against an OpenAPI/JSON Schema and return a list of
    specific violation descriptions. An empty list means the data is valid.

    Supports:
      - Untyped / unconstrained schemas (accept any value, including None/null)
      - Nullable fields (explicit nullable: True, type: 'null', or 'null' in type list)
      - anyOf, oneOf, and allOf composition
      - Objects with required fields, property validation, and additionalProperties
      - Arrays with element validation against items schema
      - Primitives (string, integer, number, boolean) with type list support
      - Root and property enum and const constraints
      - Non-strict illustrative examples
    """
    violations = []
    if not isinstance(schema, dict) or not schema:
        return violations

    prefix = f'Field "{path}"' if path else 'Root'

    # -------------------------
    # Null handling
    # -------------------------
    if data is None:
        if schema.get("nullable") is True:
            return violations
        if schema.get("type") == "null":
            return violations
        if isinstance(schema.get("type"), list) and "null" in schema["type"]:
            return violations
        if "anyOf" in schema and isinstance(schema["anyOf"], list):
            if any(len(find_schema_violations(None, opt, strict_examples, path)) == 0 for opt in schema["anyOf"]):
                return violations
        if "oneOf" in schema and isinstance(schema["oneOf"], list):
            if sum(1 for opt in schema["oneOf"] if len(find_schema_violations(None, opt, strict_examples, path)) == 0) == 1:
                return violations
        if "allOf" in schema and isinstance(schema["allOf"], list):
            if all(len(find_schema_violations(None, opt, strict_examples, path)) == 0 for opt in schema["allOf"]):
                return violations
        if "enum" in schema and None in schema["enum"]:
            return violations
        if "const" in schema and schema["const"] is None:
            return violations
        # In JSON Schema, an unconstrained schema (without a "type" keyword) allows any value, including null
        if "type" not in schema:
            return violations

        violations.append(f"{prefix}: null value not permitted by schema")
        return violations

    # -------------------------
    # anyOf / oneOf / allOf composition
    # -------------------------
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        if any(len(find_schema_violations(data, opt, strict_examples, path)) == 0 for opt in schema["anyOf"]):
            return violations
        violations.append(f"{prefix}: does not match any allowed anyOf schema")
        return violations

    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        matches = [opt for opt in schema["oneOf"] if len(find_schema_violations(data, opt, strict_examples, path)) == 0]
        if len(matches) == 1:
            return violations
        violations.append(f"{prefix}: matches {len(matches)} oneOf schemas (expected exactly 1)")
        return violations

    if "allOf" in schema and isinstance(schema["allOf"], list):
        for opt in schema["allOf"]:
            sub_errs = find_schema_violations(data, opt, strict_examples, path)
            violations.extend(sub_errs)
        if violations:
            return violations

    # -------------------------
    # const / enum constraints
    # -------------------------
    if "const" in schema and data != schema["const"]:
        violations.append(f"{prefix}: expected const {schema['const']!r}, received {data!r}")
        return violations

    enum_values = schema.get("enum")
    if enum_values is not None and data not in enum_values:
        violations.append(f"{prefix}: value {data!r} not in permitted enum {enum_values}")
        return violations

    # -------------------------
    # Strict example check (disabled by default)
    # -------------------------
    example = schema.get("example")
    if example is not None and strict_examples:
        if data != example:
            violations.append(f"{prefix}: value {data!r} does not match strict example {example!r}")
            return violations

    schema_type = schema.get("type")
    types = schema_type if isinstance(schema_type, list) else ([schema_type] if schema_type else [])

    # -------------------------
    # Primitive types checking
    # -------------------------
    if types:
        type_matched = False
        for t in types:
            if t == "string" and isinstance(data, str):
                type_matched = True
                break
            elif t == "integer" and isinstance(data, int) and not isinstance(data, bool):
                type_matched = True
                break
            elif t == "number" and isinstance(data, (int, float)) and not isinstance(data, bool):
                type_matched = True
                break
            elif t == "boolean" and isinstance(data, bool):
                type_matched = True
                break
            elif t == "array" and isinstance(data, list):
                type_matched = True
                break
            elif t == "object" and isinstance(data, dict):
                type_matched = True
                break
            elif t == "null" and data is None:
                type_matched = True
                break
        if not type_matched:
            expected_desc = "/".join(types)
            violations.append(f"{prefix}: expected {expected_desc}, received {type(data).__name__}")
            return violations

    # -------------------------
    # Array handling
    # -------------------------
    if (schema_type == "array" or "array" in types) and isinstance(data, list):
        items_schema = schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            for idx, item in enumerate(data):
                item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                sub_errs = find_schema_violations(item, items_schema, strict_examples, item_path)
                violations.extend(sub_errs)

    # -------------------------
    # Object handling
    # -------------------------
    is_object_schema = (
        schema_type == "object"
        or "object" in types
        or "properties" in schema
        or "required" in schema
    )
    if is_object_schema and isinstance(data, dict):
        required = schema.get("required", [])
        for req in required:
            if req not in data:
                violations.append(f'{prefix}: missing required property "{req}"')

        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in data:
                prop_path = f"{path}.{prop_name}" if path else prop_name
                sub_errs = find_schema_violations(data[prop_name], prop_schema, strict_examples, prop_path)
                violations.extend(sub_errs)

        # additionalProperties check
        add_props = schema.get("additionalProperties")
        if add_props is False:
            extra_keys = [k for k in data if k not in properties]
            if extra_keys:
                violations.append(f"{prefix}: unexpected additional properties {extra_keys}")
        elif isinstance(add_props, dict):
            for k, v in data.items():
                if k not in properties:
                    item_path = f"{path}.{k}" if path else k
                    violations.extend(find_schema_violations(v, add_props, strict_examples, item_path))

    return violations


def validate_schema(data, schema, strict_examples=False):
    """
    Validate response data against an OpenAPI/JSON Schema.
    Returns True if valid, False if violations exist.
    """
    return len(find_schema_violations(data, schema, strict_examples=strict_examples)) == 0