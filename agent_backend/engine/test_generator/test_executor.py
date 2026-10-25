import sys
import os
import json
import ipaddress
import socket
import requests
from urllib.parse import urlparse

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_DEBUG_DIAGNOSTICS = os.getenv("DEBUG_DIAGNOSTICS", "false").lower() in ("true", "1", "yes")


def _debug_log(*args, **kwargs):
    if _DEBUG_DIAGNOSTICS:
        print("[DIAGNOSTIC]", *args, **kwargs)


# Project paths

ENGINE_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

AGENT_BACKEND_ROOT = os.path.dirname(ENGINE_ROOT)

PROJECT_ROOT = os.path.dirname(AGENT_BACKEND_ROOT)

TARGET_API_ROOT = os.path.join(
    PROJECT_ROOT,
    "target_api"
)

# Add the correct folders to Python's import path
for folder in [
    ENGINE_ROOT,
    AGENT_BACKEND_ROOT,
    PROJECT_ROOT
]:
    if folder not in sys.path:
        sys.path.insert(0, folder)

from bug_report.bug_report_generator import (
    generate_bug_report
)

from test_generator.rule_based_generator import (
    generate_all_tests,
    get_expected_success_response,
    generate_path_params
)

from test_generator.response_validator import (
    validate_response
)

from parser.openapi_parser import (
    load_openapi,
    extract_endpoints
)

from ai_generator.ai_test_generator import (
    generate_ai_tests
)

from ai_analyzer.ai_failure_analyzer import (
    analyze_failure
)

from db_operations import (
    create_test_run,
    save_test_result,
    save_bug_report
)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL = DEFAULT_BASE_URL

# Private / link-local / loopback IP ranges that must not be reachable
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),        # private class A
    ipaddress.ip_network("172.16.0.0/12"),     # private class B
    ipaddress.ip_network("192.168.0.0/16"),    # private class C
    ipaddress.ip_network("169.254.0.0/16"),    # link-local (metadata)
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 private
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]

# Callers running against a deliberate local API (tunnels, local dev) can set
# ALLOW_LOCAL_TARGETS=true to bypass the SSRF check.
_ALLOW_LOCAL = os.getenv("ALLOW_LOCAL_TARGETS", "false").lower() in ("true", "1", "yes")


def _validate_target_url(url: str) -> None:
    """
    Raise ValueError if *url* resolves to a private/loopback/metadata address
    or uses a non-HTTP(S) scheme.
    Set ALLOW_LOCAL_TARGETS=true to skip this check for local development.
    """
    if _ALLOW_LOCAL:
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"SSRF protection: scheme '{parsed.scheme}' is not allowed. "
            f"Only http:// and https:// are permitted."
        )

    hostname = parsed.hostname or ""
    try:
        resolved_ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        # Cannot resolve — allow to fail naturally at request time
        return

    try:
        addr = ipaddress.ip_address(resolved_ip)
    except ValueError:
        return

    for network in _BLOCKED_NETWORKS:
        if addr in network:
            raise ValueError(
                f"SSRF protection: target URL '{url}' resolves to a "
                f"private/loopback/metadata IP address ({resolved_ip}). "
                f"Set ALLOW_LOCAL_TARGETS=true to test local APIs."
            )


def build_url(endpoint, path_params):
    """
    Replace path parameters with actual values.

    Example:
    /users/{user_id}
    +
    {"user_id": 1}

    becomes:
    /users/1
    """

    url = endpoint

    for name, value in path_params.items():

        url = url.replace(
            "{" + name + "}",
            str(value)
        )

    return url


def sort_tests_for_execution(tests):
    """
    Sort tests so destructive DELETE operations run last,
    preventing premature deletion of data needed by preceding tests.
    """
    tests.sort(
        key=lambda test: (
            test.get("method", "").upper() == "DELETE"
        )
    )
    return tests


def execute_test(test, base_url=DEFAULT_BASE_URL):
    """
    Execute one generated test case.
    """

    method = test["method"]
    endpoint = test["endpoint"]

    request_data = test["request"]

    path_params = request_data.get(
        "path_params",
        {}
    )

    query_params = request_data.get(
        "query_params",
        {}
    )

    headers = request_data.get(
        "headers",
        {}
    )

    body = request_data.get(
        "body"
    )

    # Build URL
    url = build_url(
        endpoint,
        path_params
    )

    full_url = base_url.rstrip("/") + url

    print("\n" + "=" * 70)

    print(
        f"Executing {test['test_id']}"
    )

    print(
        f"Request: {method} {full_url}"
    )

    # Display request body; fallback to ensure_ascii=True if terminal cannot encode Unicode
    if body:
        try:
            body_str = json.dumps(body, ensure_ascii=False)
            print(f"Body: {body_str}")
        except Exception:
            try:
                body_str = json.dumps(body, ensure_ascii=True)
                print(f"Body: {body_str}")
            except Exception:
                print("Body: <unprintable body>")
    else:
        print("Body: None")

    try:

        # SSRF protection: validate the target URL before sending the request.
        _validate_target_url(full_url)

        response = requests.request(
            method=method,
            url=full_url,
            params=query_params,
            headers=headers,
            json=body,
            timeout=30,          # prevent infinite hangs on slow/unresponsive targets
            allow_redirects=True
        )

        print(
            f"Actual status: "
            f"{response.status_code}"
        )

        try:

            response_body = response.json()

        except ValueError:

            response_body = response.text

        try:
            response_body_str = json.dumps(response_body, ensure_ascii=False)
            print(f"Response: {response_body_str}")
        except Exception:
            try:
                response_body_str = json.dumps(response_body, ensure_ascii=True)
                print(f"Response: {response_body_str}")
            except Exception:
                print("Response: <unprintable response>")

        # Carry provenance fields from the test case into the result so
        # validate_response() can classify uncertain expectations correctly.
        result = {
            "test_id": test["test_id"],
            "endpoint": endpoint,
            "method": method,
            "request": request_data,
            "expected": test["expected"],
            "actual": {
                "status_code": response.status_code,
                "body": response_body
            }
        }
        for provenance_key in (
            "expected_source",
            "expectation_confidence",
            "requires_review",
            "review_reason",
        ):
            if provenance_key in test:
                result[provenance_key] = test[provenance_key]
        return result

    except requests.RequestException as error:

        print(
            f"Request failed: {error}"
        )

        result = {
            "test_id": test["test_id"],
            "endpoint": endpoint,
            "method": method,
            "request": request_data,
            "expected": test["expected"],
            "actual": {
                "status_code": None,
                "body": None,
                "error": str(error)
            }
        }
        for provenance_key in (
            "expected_source",
            "expectation_confidence",
            "requires_review",
            "review_reason",
        ):
            if provenance_key in test:
                result[provenance_key] = test[provenance_key]
        return result
        
def run_all_tests(
    base_url=DEFAULT_BASE_URL,
    openapi_url=None
    ):
    if openapi_url is None:
        openapi_url = base_url.rstrip("/") + "/openapi.json"

    # ── Step 1: Reset demo data (local API only) ────────────────────────
    reset_ok = True

    if base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/"):
        try:
            reset_response = requests.post(
                f"{base_url.rstrip('/')}/reset",
                timeout=5
            )

            if reset_response.status_code == 200:
                print("[Reset] Test data restored successfully.")
            else:
                reset_ok = False
                print(
                    "[Reset] WARNING: /reset returned "
                    f"{reset_response.status_code}. "
                    "Tests that depend on user ID 1 may fail."
                )

        except requests.RequestException as e:
            reset_ok = False
            print(
                f"[Reset] WARNING: Could not reach target API: {e}. "
                "Is the target API running on port 8000? "
                "Tests that depend on user ID 1 may fail."
            )

    # ── Step 2: Load OpenAPI spec ONCE and reuse it everywhere ──────────
    print("\nLoading OpenAPI specification...")
    openapi_data = load_openapi(openapi_url)
    endpoints    = extract_endpoints(openapi_data)
    print(f"Found {len(endpoints)} endpoints.")

    # ── Step 3: Generate rule-based tests ───────────────────────────────
    print("\nGenerating test cases...\n")

    # Pass already-loaded openapi_data to avoid a second network fetch
    all_tests = generate_all_tests(openapi_url, openapi_data=openapi_data)

    print(f"Rule-based tests generated: {len(all_tests)}")

    # ── Step 4: Generate AI tests ────────────────────────────────────────
    ai_tests = []

    for endpoint in endpoints:

        # Currently generate AI tests only for POST /users
        if endpoint.get("request_body"):

            print(f"[AI Generator] Endpoint: {endpoint['method']} {endpoint['path']}")

            generated_tests = generate_ai_tests(endpoint)
            
            print(
                f"[AI Generator] Returned {len(generated_tests)} tests"
            )
            
            # Add expected response schema to AI tests
            expected_schema = get_expected_success_response(
                endpoint,
                openapi_data
            )
            print(
                "[AI Generator] Expected success schema:",
                expected_schema
            )
            
            for test in generated_tests:
                test.setdefault("request", {})

                path_params = test["request"].setdefault(
                    "path_params", {}
                )

                # Populate path parameters generically from OpenAPI parameter specs
                for param_name, param_val in generate_path_params(endpoint).items():
                    path_params.setdefault(param_name, param_val)

                # Fallback for any template parameters in path not explicitly listed
                import re
                for param_name in re.findall(r"\{([^}]+)\}", endpoint.get("path", "")):
                    path_params.setdefault(param_name, 1)

                # Preserve the AI-generated expected status code.
                test.setdefault("expected", {})

                # Attach the success response schema only when the
                # expected status represents a successful response.
                expected_status = test["expected"].get("status_code")

                if expected_status is not None and 200 <= expected_status < 300:
                    test["expected"]["response_schema"] = expected_schema

            ai_tests.extend(generated_tests)

    # Give AI tests unique IDs
    for index, test in enumerate(ai_tests, start=1):
        test["test_id"] = f"AI-TC-{index}"

    print(f"AI-generated tests: {len(ai_tests)}")

    # Combine rule-based + AI tests
    all_tests.extend(ai_tests)
    
    # Run destructive DELETE tests last so they do not
    # remove users needed by GET or PUT tests.
    sort_tests_for_execution(all_tests)
    
    print(f"Total tests: {len(all_tests)}")
    
    results = []
    
    for test in all_tests:
        _debug_log(
            f"Before execution: test_id={test.get('test_id')}, "
            f"endpoint={test.get('endpoint')}, "
            f"expected_status_code={test.get('expected', {}).get('status_code')}, "
            f"expected_source={test.get('expected_source')}, "
            f"expectation_confidence={test.get('expectation_confidence')}, "
            f"requires_review={test.get('requires_review')}"
        )

        result = execute_test(test, base_url=base_url)

        _debug_log(
            f"Before validation: test_id={result.get('test_id')}, "
            f"actual_status={result.get('actual', {}).get('status_code')}, "
            f"expected_status_code={result.get('expected', {}).get('status_code')}, "
            f"expected_source={result.get('expected_source')}, "
            f"expectation_confidence={result.get('expectation_confidence')}, "
            f"requires_review={result.get('requires_review')}"
        )

        validated_result = validate_response(
            result)

        results.append(
            validated_result
        )

    print("\n")
    print("=" * 70)
    print("TEST EXECUTION SUMMARY")
    print("=" * 70)

    passed = 0
    failed = 0
    bug_counter = 0

    for result in results:

        print(
            f"{result['test_id']} "
            f"{result['status']}"
        )

        if result["status"] == "PASS":

            passed += 1

        else:

            failed += 1

            print(
                f"Failure Reason: "
                f"{result['failure_reason']}"
            )

            # ── Failure classification and routing ───────────────────────────
            # Only confirmed API defects generate AI analysis + bug reports.
            # All other failure types are logged with a diagnostic label and
            # stored as test results, but do NOT produce bug reports.

            failure_type = result.get("failure_type")

            if failure_type == "UNCERTAIN_EXPECTATION":
                print(
                    "[Validator] UNCERTAIN_EXPECTATION — skipping bug report "
                    "(AI expectation was low-confidence or flagged for review)."
                )
                result["ai_analysis"] = None
                result["bug_report"] = None
                continue

            if failure_type == "RESOURCE_NOT_FOUND":
                print(
                    "[Validator] RESOURCE_NOT_FOUND — skipping bug report "
                    "(resource likely doesn't exist; no setup step was run)."
                )
                result["ai_analysis"] = None
                result["bug_report"] = None
                continue

            if failure_type == "NEEDS_REVIEW":
                print(
                    "[Validator] NEEDS_REVIEW — skipping bug report "
                    "(both expected and actual are 4xx; test expectation may be wrong)."
                )
                result["ai_analysis"] = None
                result["bug_report"] = None
                continue

            if failure_type == "INFRASTRUCTURE_FAILURE":
                print(
                    "[Validator] INFRASTRUCTURE_FAILURE — skipping bug report "
                    "(network/timeout error; not an API defect)."
                )
                result["ai_analysis"] = None
                result["bug_report"] = None
                continue

            # Only API_DEFECT failures reach this point.
            if failure_type != "API_DEFECT":
                # Unknown failure type — log and skip to be safe.
                print(
                    f"[Validator] Unknown failure_type '{failure_type}' — "
                    "skipping bug report."
                )
                result["ai_analysis"] = None
                result["bug_report"] = None
                continue

            # Analyze confirmed API defect using AI
            analysis = analyze_failure(
                result
            )

            result["ai_analysis"] = analysis

            # If the AI analyzer itself failed, preserve the test result but
            # do NOT generate a bug report based on a failed analysis.
            if analysis.get("analyzer_failed"):
                print(
                    "[AI Analyzer] Analysis unavailable — skipping bug report "
                    "for this failure (AI analyzer was unreachable or returned "
                    "an invalid response). The FAIL status is preserved."
                )
                result["bug_report"] = None
                continue

            bug_counter += 1
            bug_report = generate_bug_report(result, bug_counter=bug_counter)

            result["bug_report"] = bug_report

            print("\nBUG REPORT")
            print("-" * 50)

            for key, value in bug_report.items():
                print(f"{key}: {value}")

            print("\nAI FAILURE ANALYSIS")
            print("-" * 50)

            print(
                f"Summary: "
                f"{analysis['summary']}"
            )

            print(
                f"Possible Cause: "
                f"{analysis['possible_cause']}"
            )

            print(
                f"Severity: "
                f"{analysis['severity']}"
            )

            print(
                f"Recommendation: "
                f"{analysis['recommendation']}"
            )

    # Final summary
    print("\n")
    print("=" * 70)
    print("FINAL TEST EXECUTION SUMMARY")
    print("=" * 70)

    print(
        f"Total: {len(results)}"
    )

    print(
        f"Passed: {passed}"
    )

    print(
        f"Failed: {failed}"
    )
    
    # ==============================
    # SAVE TEST RUN TO DATABASE
    # ==============================
    
    pass_rate = round(
        (passed / len(results)) * 100,
        2
    ) if results else 0
    
    
    run_id = create_test_run(
        total_tests=len(results),
        passed_tests=passed,
        failed_tests=failed
    )
    
    print(
        f"Database Run ID: {run_id}"
    )
    
    
    # Save every test result
    for result in results:
        save_test_result(
            run_id,
            result
        )

        if result.get("bug_report"):
            save_bug_report(
                run_id,
                result
            )
    
    
    print(
        "Test results saved to database successfully!"
    )
    
    
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "run_id": run_id,
        "results": results
    }
    
if __name__ == "__main__":
    run_all_tests()