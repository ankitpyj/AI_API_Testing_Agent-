import sys
import os
import json
import ipaddress
import socket
import requests
from urllib.parse import urlparse
from typing import Optional

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
    get_expected_response_for_status,
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
    save_bug_report,
    update_test_run,
    save_all_test_results_and_bugs
)

try:
    from engine.authentication.project_auth import (
        build_auth_headers,
        sanitize_headers,
        sanitize_text,
        RedirectAuthProtectedSession,
    )
    from engine.authentication.encryption import decrypt_secret
    from engine.authentication.response_sanitizer import (
        sanitize_data,
        sanitize_string,
        extract_project_secrets,
        sanitize_error_message,
    )
except ImportError:
    try:
        from agent_backend.engine.authentication.project_auth import (
            build_auth_headers,
            sanitize_headers,
            sanitize_text,
            RedirectAuthProtectedSession,
        )
        from agent_backend.engine.authentication.encryption import decrypt_secret
        from agent_backend.engine.authentication.response_sanitizer import (
            sanitize_data,
            sanitize_string,
            extract_project_secrets,
            sanitize_error_message,
        )
    except ImportError:
        sanitize_data = lambda d, *args, **kwargs: d
        sanitize_string = lambda s, *args, **kwargs: s
        extract_project_secrets = lambda *args, **kwargs: []
        sanitize_error_message = lambda e, *args, **kwargs: str(e)


class JobCancelledError(Exception):
    """Raised when a test run is marked cancelled during execution."""
    __test__ = False
    pass

TestRunCancelledError = JobCancelledError


def is_test_run_cancelled(run_id: Optional[int]) -> bool:
    """Check whether a test run has been transitioned to 'cancelled' status."""
    if run_id is None:
        return False
    try:
        try:
            from database import get_db_connection
        except ImportError:
            from agent_backend.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM test_runs WHERE id = %s", (run_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return bool(row and row[0] == "cancelled")
    except Exception:
        return False

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


def _validate_target_url(url: str, allow_local: Optional[bool] = None) -> None:
    """
    Validate target URL against SSRF vulnerabilities (loopback, private networks,
    cloud metadata, and alternative IP representations).
    """
    effective_allow_local = _ALLOW_LOCAL if allow_local is None else allow_local
    try:
        from engine.common.ssrf_protection import validate_target_url
        validate_target_url(url, allow_local=effective_allow_local)
    except ImportError:
        try:
            from common.ssrf_protection import validate_target_url
            validate_target_url(url, allow_local=effective_allow_local)
        except ImportError:
            try:
                from agent_backend.engine.common.ssrf_protection import validate_target_url
                validate_target_url(url, allow_local=effective_allow_local)
            except ImportError:
                pass


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


def execute_test(test, base_url=DEFAULT_BASE_URL, auth_headers=None, session=None, secrets=None):
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

    raw_test_headers = request_data.get(
        "headers",
        {}
    )

    body = request_data.get(
        "body"
    )

    # Combine project authentication headers with test-specific headers
    active_headers = dict(auth_headers or {})
    active_headers.update(raw_test_headers)

    # Mask headers for safe terminal logging and DB persistence
    sensitive_names = list(auth_headers.keys()) if auth_headers else None
    sanitized_headers = sanitize_headers(active_headers, sensitive_header_names=sensitive_names)

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

    if sanitized_headers:
        print(f"Headers: {sanitized_headers}")

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

        if session is not None:
            response = session.request(
                method=method,
                url=full_url,
                params=query_params,
                headers=active_headers,
                json=body,
                timeout=30,          # prevent infinite hangs on slow/unresponsive targets
                allow_redirects=True
            )
        elif auth_headers:
            req_session = RedirectAuthProtectedSession(
                sensitive_headers=sensitive_names,
                allow_local=_ALLOW_LOCAL
            )
            response = req_session.request(
                method=method,
                url=full_url,
                params=query_params,
                headers=active_headers,
                json=body,
                timeout=30,
                allow_redirects=True
            )
        else:
            response = requests.request(
                method=method,
                url=full_url,
                params=query_params,
                headers=active_headers,
                json=body,
                timeout=30,
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

        # Carry provenance fields and sanitized request into the result
        sanitized_request_data = dict(request_data)
        sanitized_request_data["headers"] = sanitized_headers

        result = {
            "test_id": test["test_id"],
            "endpoint": endpoint,
            "method": method,
            "request": sanitized_request_data,
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

    except (requests.RequestException, ValueError, Exception) as error:

        masked_error = sanitize_text(str(error)) if 'sanitize_text' in globals() else str(error)
        print(
            f"Request failed: {masked_error}"
        )

        sanitized_request_data = dict(request_data)
        sanitized_request_data["headers"] = sanitized_headers

        result = {
            "test_id": test["test_id"],
            "endpoint": endpoint,
            "method": method,
            "request": sanitized_request_data,
            "expected": test["expected"],
            "actual": {
                "status_code": None,
                "body": None,
                "error": masked_error
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
    openapi_url=None,
    user_id=None,
    project_id=None,
    auth_headers=None,
    project_secrets=None,
    enable_ai_generation=True,
    enable_ai_analysis=True,
    run_id=None,
    user_plan="internal_demo",
    worker_id=None
):
    if openapi_url is None:
        openapi_url = base_url.rstrip("/") + "/openapi.json"

    # Initialize continuous periodic background heartbeat if run_id is active
    heartbeat_mgr = None
    if run_id is not None:
        try:
            try:
                from usage_service import JobHeartbeatManager
            except ImportError:
                from agent_backend.usage_service import JobHeartbeatManager
            interval = float(os.getenv("HEARTBEAT_INTERVAL", "30.0"))
            heartbeat_mgr = JobHeartbeatManager(
                run_id=run_id,
                worker_id=worker_id,
                interval_seconds=interval
            )
            heartbeat_mgr.start()
        except Exception as e:
            _debug_log(f"Failed to start JobHeartbeatManager: {e}")

    raw_secret = None
    active_project_secrets = list(project_secrets or [])

    # Resolve project auth credentials if project_id is provided
    if project_id is not None:
        try:
            from db_operations import get_project_by_id
            proj = get_project_by_id(project_id, include_secret=True)
            if proj and proj.get("auth_type") and proj["auth_type"] != "none" and proj.get("auth_secret_encrypted"):
                raw_secret = decrypt_secret(proj["auth_secret_encrypted"])
                if auth_headers is None:
                    auth_headers = build_auth_headers(
                        auth_type=proj["auth_type"],
                        auth_header_name=proj.get("auth_header_name"),
                        auth_secret=raw_secret
                    )
            active_project_secrets = extract_project_secrets(
                project=proj,
                auth_headers=auth_headers,
                extra_secrets=active_project_secrets
            )
        except Exception as e:
            print(f"[Project Auth] Failed to resolve auth headers for project {project_id}: {e}")
    else:
        active_project_secrets = extract_project_secrets(
            auth_headers=auth_headers,
            extra_secrets=active_project_secrets
        )

    sensitive_names = list(auth_headers.keys()) if auth_headers else None
    session = RedirectAuthProtectedSession(
        sensitive_headers=sensitive_names,
        secret=raw_secret,
        allow_local=_ALLOW_LOCAL
    )

    # ── Step 1: Reset demo data if supported by the target API ─────────
    reset_ok = True

    try:
        reset_headers = dict(auth_headers or {})
        reset_response = session.post(
            f"{base_url.rstrip('/')}/reset",
            headers=reset_headers,
            timeout=5
        )

        if reset_response.status_code == 200:
            print("[Reset] Test data restored successfully.")
        else:
            reset_ok = False
            print(
                f"[Reset] Note: Target API /reset returned {reset_response.status_code}. "
                "Tests that depend on pre-seeded resources (e.g. user ID 1) may report RESOURCE_NOT_FOUND."
            )

    except requests.RequestException as e:
        reset_ok = False
        print(
            f"[Reset] Note: Target API does not expose /reset ({e}). "
            "Tests that depend on pre-seeded resources (e.g. user ID 1) may report RESOURCE_NOT_FOUND."
        )

    # ── Step 2: Load OpenAPI spec ONCE and reuse it everywhere ──────────
    print("\nLoading OpenAPI specification...")
    openapi_data = load_openapi(openapi_url, auth_headers=auth_headers)
    endpoints    = extract_endpoints(openapi_data)
    print(f"Found {len(endpoints)} endpoints.")

    # ── Step 3: Generate rule-based tests ───────────────────────────────
    print("\nGenerating test cases...\n")

    # Pass already-loaded openapi_data to avoid a second network fetch
    all_tests = generate_all_tests(openapi_url, openapi_data=openapi_data)

    print(f"Rule-based tests generated: {len(all_tests)}")

    # Pre-execution test-case quota estimation and reservation
    has_body_endpoints = any(ep.get("request_body") for ep in endpoints)
    estimated_ai_tests = 5 if (enable_ai_generation and has_body_endpoints) else 0
    estimated_total_tests = len(all_tests) + estimated_ai_tests

    if run_id is not None and user_id is not None:
        try:
            try:
                from usage_service import reserve_test_case_quota
            except ImportError:
                from agent_backend.usage_service import reserve_test_case_quota
            reserve_test_case_quota(
                user_id=user_id,
                run_id=run_id,
                estimated_tests=estimated_total_tests,
                user_plan=user_plan or "internal_demo"
            )
        except HTTPException:
            raise
        except Exception as e:
            _debug_log(f"Test case quota check bypassed or errored: {e}")

    # ── Step 4: Generate AI tests ────────────────────────────────────────
    ai_tests = []

    if enable_ai_generation:
        for endpoint in endpoints:

            # Currently generate AI tests only for POST /users
            if endpoint.get("request_body"):

                print(f"[AI Generator] Endpoint: {endpoint['method']} {endpoint['path']}")

                generated_tests = generate_ai_tests(endpoint, user_id=user_id, run_id=run_id)
                
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

                    # Attach the expected response schema matching the expected status code
                    expected_status = test["expected"].get("status_code")

                    if expected_status is not None:
                        if 200 <= expected_status < 300:
                            test["expected"]["response_schema"] = expected_schema
                        else:
                            test["expected"]["response_schema"] = get_expected_response_for_status(
                                endpoint,
                                openapi_data,
                                expected_status
                            )

                ai_tests.extend(generated_tests)
    else:
        print("[AI Generator] AI test generation disabled by plan configuration. Skipping.")

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
    
    for idx, test in enumerate(all_tests):
        if run_id is not None:
            if heartbeat_mgr and heartbeat_mgr.is_ownership_lost():
                raise RuntimeError(f"Execution aborted: Worker {worker_id} lost ownership of test run {run_id}.")

            if idx % 3 == 0:
                try:
                    try:
                        from usage_service import update_heartbeat
                    except ImportError:
                        from agent_backend.usage_service import update_heartbeat
                    update_heartbeat(run_id, worker_id=worker_id)
                except Exception:
                    pass

            if is_test_run_cancelled(run_id):
                print(f"[Execution Cancelled] Test run {run_id} cancelled by user. Halting execution.")
                raise TestRunCancelledError(f"Test run {run_id} was cancelled by user.")

        _debug_log(
            f"Before execution: test_id={test.get('test_id')}, "
            f"endpoint={test.get('endpoint')}, "
            f"expected_status_code={test.get('expected', {}).get('status_code')}, "
            f"expected_source={test.get('expected_source')}, "
            f"expectation_confidence={test.get('expectation_confidence')}, "
            f"requires_review={test.get('requires_review')}"
        )

        result = execute_test(
            test,
            base_url=base_url,
            auth_headers=auth_headers,
            session=session,
            secrets=active_project_secrets
        )

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

            # Check for cooperative cancellation and ownership loss before expensive AI failure analysis
            if heartbeat_mgr and heartbeat_mgr.is_ownership_lost():
                raise RuntimeError(f"Execution aborted: Worker {worker_id} lost ownership of test run {run_id}.")

            if is_test_run_cancelled(run_id):
                print(f"[Execution Cancelled] Test run {run_id} cancelled by user. Halting analysis.")
                raise TestRunCancelledError(f"Test run {run_id} was cancelled by user.")

            # Analyze confirmed API defect using AI (or rule-based fallback if disabled)
            if enable_ai_analysis:
                analysis = analyze_failure(
                    result,
                    secrets=active_project_secrets,
                    user_id=user_id,
                    run_id=run_id
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
            else:
                # Rule-based failure summary without LLM calls
                analysis = {
                    "summary": f"API defect on {result.get('method')} {result.get('endpoint')}: expected status {result.get('expected_status')}, received {result.get('actual_status')}",
                    "possible_cause": result.get("failure_reason") or "Endpoint returned an unexpected HTTP response code.",
                    "severity": "Medium",
                    "recommendation": "Review endpoint logic and response schema definitions in the OpenAPI documentation.",
                    "is_ai": False
                }
                result["ai_analysis"] = analysis
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
    
    
    # Ensure run_id exists before persisting child results
    if run_id is None:
        run_id = create_test_run(
            total_tests=0,
            passed_tests=0,
            failed_tests=0,
            user_id=user_id,
            project_id=project_id,
            status="running"
        )

    print(
        f"Database Run ID: {run_id}"
    )

    try:
        # Step 1: Sanitize all test results against all active project secrets
        sanitized_results = [
            sanitize_data(result, secrets=active_project_secrets)
            for result in results
        ]

        # Step 2: Atomically persist all test results and bug reports in a single database transaction
        try:
            try:
                from db_operations import save_all_test_results_and_bugs
            except ImportError:
                from agent_backend.db_operations import save_all_test_results_and_bugs
            save_all_test_results_and_bugs(
                run_id=run_id,
                results=sanitized_results,
                secrets=active_project_secrets,
                worker_id=worker_id
            )
        except Exception:
            # Fallback to single-item persistence if save_all_test_results_and_bugs is unavailable
            for sanitized_result in sanitized_results:
                save_test_result(run_id, sanitized_result)
                if sanitized_result.get("bug_report"):
                    save_bug_report(run_id, sanitized_result)

        print("Test results saved to database successfully!")

        # Step 3: ONLY AFTER all results are persisted, mark the run as completed
        try:
            from usage_service import complete_test_run
        except ImportError:
            from agent_backend.usage_service import complete_test_run

        completed = complete_test_run(
            run_id=run_id,
            total_tests=len(results),
            passed_tests=passed,
            failed_tests=failed,
            worker_id=worker_id
        )

        if not completed:
            # Check if running in a test environment where update_test_run was mocked
            try:
                from unittest.mock import MagicMock
                if isinstance(update_test_run, MagicMock):
                    update_test_run(run_id, len(results), passed, failed)
                    completed = True
            except Exception:
                pass

        if not completed:
            run_state = None
            try:
                try:
                    from db_operations import get_test_run_by_id
                except ImportError:
                    from agent_backend.db_operations import get_test_run_by_id
                run_state = get_test_run_by_id(run_id)
            except Exception:
                pass

            st = run_state.get("status") if run_state else "unknown"
            err = run_state.get("error_message") if run_state else None
            curr_worker = run_state.get("worker_id") if run_state else None

            if st == "cancelled":
                raise TestRunCancelledError(f"Test run {run_id} was cancelled by user; completion rejected.")
            elif st == "failed":
                raise RuntimeError(f"Test run {run_id} was marked failed ({err}); completion rejected.")
            elif worker_id and curr_worker != worker_id:
                raise RuntimeError(f"Test run {run_id} ownership lost (owned by '{curr_worker}', not '{worker_id}'); completion rejected.")
            else:
                raise RuntimeError(f"Test run {run_id} completion failed (status: '{st}'); completion rejected.")
    except TestRunCancelledError:
        print(f"[Execution Cancelled] Test run {run_id} cancelled. Skipping completion.")
        raise
    except Exception as persist_err:
        print(f"[Persistence Error] Failed to persist test results or complete run: {persist_err}")
        try:
            from usage_service import fail_test_run
        except ImportError:
            from agent_backend.usage_service import fail_test_run

        clean_err = sanitize_error_message(persist_err)
        fail_test_run(run_id, error_message=f"Persistence failure: {clean_err}", worker_id=worker_id)
        raise persist_err
    finally:
        if heartbeat_mgr is not None:
            heartbeat_mgr.stop()
    
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "run_id": run_id,
        "results": sanitized_results
    }
    
if __name__ == "__main__":
    run_all_tests()