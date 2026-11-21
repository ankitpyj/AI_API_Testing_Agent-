import json
from urllib.parse import urlparse, urlunparse
from typing import Optional, Dict, Any, List

try:
    from database import get_db_connection
except ImportError:
    from agent_backend.database import get_db_connection

try:
    from engine.authentication.response_sanitizer import sanitize_data, sanitize_string
except ImportError:
    try:
        from agent_backend.engine.authentication.response_sanitizer import sanitize_data, sanitize_string
    except ImportError:
        sanitize_data = lambda d, *a, **k: d
        sanitize_string = lambda s, *a, **k: s


def sanitize_target_url(url: Optional[str]) -> Optional[str]:
    """
    Validate and sanitize a target API URL before database persistence.
    - Strips leading and trailing whitespace.
    - Strips any embedded userinfo credentials (username:password@) to prevent credential leakage.
    - Rejects schemes other than 'http' and 'https'.
    - Rejects URLs without a valid hostname.
    """
    if not url:
        return None
    trimmed = str(url).strip()
    if not trimmed:
        return None
    try:
        parsed = urlparse(trimmed)
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if not parsed.hostname:
            return None
        clean_netloc = parsed.hostname
        if parsed.port:
            clean_netloc = f"{clean_netloc}:{parsed.port}"
        sanitized = urlunparse((
            parsed.scheme.lower(),
            clean_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            ""
        ))
        return sanitized.rstrip("/") if not parsed.path else sanitized
    except Exception:
        return None


def create_test_run(
    total_tests=0,
    passed_tests=0,
    failed_tests=0,
    user_id=None,
    project_id=None,
    status="completed",
    base_url=None,
    openapi_url=None,
    worker_id=None,
    error_message=None
):
    connection = get_db_connection()
    cursor = connection.cursor()

    clean_base = sanitize_target_url(base_url)
    clean_openapi = sanitize_target_url(openapi_url)

    query = """
        INSERT INTO test_runs
        (total_tests, passed_tests, failed_tests, user_id, project_id, status, base_url, openapi_url, worker_id, error_message, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())
    """

    cursor.execute(
        query,
        (
            total_tests,
            passed_tests,
            failed_tests,
            user_id,
            project_id,
            status,
            clean_base,
            clean_openapi,
            worker_id,
            error_message
        )
    )

    run_id = cursor.lastrowid

    connection.commit()

    cursor.close()
    connection.close()

    return run_id


def update_test_run(
    run_id: int,
    total_tests: int,
    passed_tests: int,
    failed_tests: int,
    status: str = "completed",
    error_message: Optional[str] = None
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        completed_expr = "completed_at = UTC_TIMESTAMP()," if status in ("completed", "failed", "cancelled") else ""
        error_clause = "error_message = %s," if error_message is not None else ""

        sql = f"""
            UPDATE test_runs
            SET total_tests = %s, passed_tests = %s, failed_tests = %s,
                estimated_tests = 0, status = %s, {completed_expr} {error_clause}
                heartbeat_at = UTC_TIMESTAMP()
            WHERE id = %s
        """
        params = [total_tests, passed_tests, failed_tests, status]
        if error_message is not None:
            params.append(error_message)
        params.append(run_id)

        cursor.execute(sql, tuple(params))
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def log_ai_usage(
    user_id: int,
    run_id: Optional[int] = None,
    call_type: str = "generation",
    provider: str = "gemini",
    model: str = "gemini-flash-lite-latest",
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    status: str = "success"
) -> Optional[int]:
    """
    Record an individual LLM API call in ai_usage_logs for accurate provider cost
    and quota accounting. Does not store prompt text, API keys, or secret data.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        query = """
            INSERT INTO ai_usage_logs (
                user_id, run_id, call_type, provider, model,
                input_tokens, output_tokens, total_tokens, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (
                user_id,
                run_id,
                call_type.strip().lower(),
                provider.strip().lower(),
                model.strip(),
                input_tokens,
                output_tokens,
                total_tokens,
                status.strip().lower()
            )
        )
        log_id = cursor.lastrowid
        connection.commit()
        return log_id
    except Exception as e:
        print(f"[AI Usage Log] Warning: failed to record AI usage log: {e}")
        return None
    finally:
        cursor.close()
        connection.close()




def save_test_result(run_id, result):

    connection = get_db_connection()
    cursor = connection.cursor()

    # ==========================================
    # Expected response
    # ==========================================

    expected = result.get("expected", {})

    expected_status = (
        result.get("expected_status")
        if result.get("expected_status") is not None
        else expected.get("status_code")
    )

    # Resolve expected_body from the validated result.
    # Priority 1: flat "expected_schema" key set by validate_response()
    # Priority 2: nested "expected.response_schema" key set by generator
    # None means "no schema defined in OpenAPI" and is stored as JSON null.
    # We deliberately store None (not {}) so the dashboard can show
    # "Not specified in OpenAPI" instead of an empty object.
    if result.get("expected_schema") is not None:
        expected_body = result.get("expected_schema")
    elif expected.get("response_schema") is not None:
        expected_body = expected.get("response_schema")
    elif expected.get("schema") is not None:
        expected_body = expected.get("schema")
    elif expected.get("body") is not None:
        expected_body = expected.get("body")
    else:
        expected_body = None   # No schema defined — stored as JSON null

    # ==========================================
    # Actual response
    # ==========================================

    actual = result.get("actual", {})

    actual_status = (
        result.get("actual_status")
        if result.get("actual_status") is not None
        else actual.get("status_code")
    )

    actual_body = (
        result.get("actual_body")
        if result.get("actual_body") is not None
        else actual.get("body")
    )

    # ==========================================
    # Test category
    # ==========================================

    category = (
        "AI"
        if result.get("test_id", "").startswith("AI-")
        else "Rule-Based"
    )

    # ==========================================
    # Insert into database
    # ==========================================

    query = """
        INSERT INTO test_results
        (
            run_id,
            test_id,
            method,
            endpoint,
            category,
            status,
            failure_type,
            expected_status,
            expected_body,
            actual_status,
            request_body,
            actual_body,
            failure_reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    # Defense-in-depth: sanitize actual response body, request payload, and failure reason
    clean_actual_body = sanitize_data(actual_body)
    clean_request_body = sanitize_data(result.get("request", {}))
    clean_failure_reason = sanitize_string(result.get("failure_reason"))

    cursor.execute(
        query,
        (
            run_id,
            result.get("test_id"),
            result.get("method"),
            result.get("endpoint"),
            category,
            result.get("status"),
            result.get("failure_type"),
            expected_status,
            json.dumps(expected_body),
            actual_status,
            json.dumps(clean_request_body),
            json.dumps(clean_actual_body),
            clean_failure_reason
        )
    )

    connection.commit()

    cursor.close()
    connection.close()


def save_bug_report(run_id, result):
    bug_report = result.get("bug_report")

    if not bug_report:
        return

    connection = get_db_connection()
    cursor = connection.cursor()

    query = """
        INSERT INTO bug_reports
        (
            run_id,
            test_id,
            bug_id,
            endpoint,
            severity,
            summary,
            possible_cause,
            recommendation,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(
        query,
        (
            run_id,
            result.get("test_id"),
            bug_report.get("bug_id"),
            bug_report.get("endpoint"),
            bug_report.get("severity"),
            sanitize_string(bug_report.get("summary")),
            sanitize_string(bug_report.get("possible_cause")),
            sanitize_string(bug_report.get("recommendation")),
            bug_report.get("status", "Open")
        )
    )

    connection.commit()

    cursor.close()
    connection.close()


def save_all_test_results_and_bugs(
    run_id: int,
    results: List[Dict[str, Any]],
    secrets: Optional[List[str]] = None,
    worker_id: Optional[str] = None
) -> None:
    """
    Atomically persist all test results and bug reports for a given test run in a single
    database transaction.

    - Fences zombie workers: locks test_runs row with FOR UPDATE and verifies run exists,
      is in 'running' status, and belongs to worker_id (if supplied). Aborts and rolls back
      if ownership was lost or run was cancelled/timed out.
    - Clears any previous results/bugs for this run_id to ensure clean idempotency on retry.
    - Applies secret sanitization to all request/response bodies and failure descriptions.
    - Inserts all test_results and bug_reports.
    - Atomically commits on success.
    - On any exception: performs connection.rollback(), ensuring no partial results remain, and re-raises.
    """
    if results is None:
        return

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        # 1. Lock test_runs row and verify status and worker ownership
        cursor.execute(
            """
            SELECT id, status, worker_id
            FROM test_runs
            WHERE id = %s
            FOR UPDATE
            """,
            (run_id,)
        )
        row = cursor.fetchone()
        if not row:
            connection.rollback()
            raise ValueError(f"Cannot save results: test run {run_id} not found")

        run_status = row["status"] if isinstance(row, dict) else row[1]
        run_worker = row["worker_id"] if isinstance(row, dict) else row[2]

        if run_status != "running":
            connection.rollback()
            raise RuntimeError(
                f"Cannot save results: test run {run_id} is in status '{run_status}', not 'running'"
            )

        if worker_id is not None and run_worker is not None and run_worker != worker_id:
            connection.rollback()
            raise RuntimeError(
                f"Cannot save results: worker ownership mismatch for run {run_id} (assigned to {run_worker}, attempting write from {worker_id})"
            )

        # 2. Clean previous results if any (idempotency/retry safety)
        cursor.execute("DELETE FROM bug_reports WHERE run_id = %s", (run_id,))
        cursor.execute("DELETE FROM test_results WHERE run_id = %s", (run_id,))

        test_result_sql = """
            INSERT INTO test_results
            (
                run_id,
                test_id,
                method,
                endpoint,
                category,
                status,
                failure_type,
                expected_status,
                expected_body,
                actual_status,
                request_body,
                actual_body,
                failure_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        bug_report_sql = """
            INSERT INTO bug_reports
            (
                run_id,
                test_id,
                bug_id,
                endpoint,
                severity,
                summary,
                possible_cause,
                recommendation,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        for result in results:
            expected = result.get("expected", {})
            expected_status = (
                result.get("expected_status")
                if result.get("expected_status") is not None
                else expected.get("status_code")
            )

            if result.get("expected_schema") is not None:
                expected_body = result.get("expected_schema")
            elif expected.get("response_schema") is not None:
                expected_body = expected.get("response_schema")
            elif expected.get("schema") is not None:
                expected_body = expected.get("schema")
            elif expected.get("body") is not None:
                expected_body = expected.get("body")
            else:
                expected_body = None

            actual = result.get("actual", {})
            actual_status = (
                result.get("actual_status")
                if result.get("actual_status") is not None
                else actual.get("status_code")
            )
            actual_body = (
                result.get("actual_body")
                if result.get("actual_body") is not None
                else actual.get("body")
            )

            category = (
                "AI"
                if result.get("test_id", "").startswith("AI-")
                else "Rule-Based"
            )

            clean_actual_body = sanitize_data(actual_body, secrets=secrets)
            clean_request_body = sanitize_data(result.get("request", {}), secrets=secrets)
            clean_failure_reason = sanitize_string(result.get("failure_reason"), secrets=secrets)

            cursor.execute(
                test_result_sql,
                (
                    run_id,
                    result.get("test_id"),
                    result.get("method"),
                    result.get("endpoint"),
                    category,
                    result.get("status"),
                    result.get("failure_type"),
                    expected_status,
                    json.dumps(expected_body),
                    actual_status,
                    json.dumps(clean_request_body),
                    json.dumps(clean_actual_body),
                    clean_failure_reason
                )
            )

            bug = result.get("bug_report")
            if bug:
                cursor.execute(
                    bug_report_sql,
                    (
                        run_id,
                        result.get("test_id"),
                        bug.get("bug_id"),
                        bug.get("endpoint"),
                        bug.get("severity"),
                        sanitize_string(bug.get("summary"), secrets=secrets),
                        sanitize_string(bug.get("possible_cause"), secrets=secrets),
                        sanitize_string(bug.get("recommendation"), secrets=secrets),
                        bug.get("status", "Open")
                    )
                )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_test_runs(user_id=None, project_id=None):

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    if user_id is not None and project_id is not None:
        query = """
            SELECT
                t.id,
                t.user_id,
                t.project_id,
                p.project_name,
                t.created_at,
                t.started_at,
                t.completed_at,
                t.total_tests,
                t.passed_tests,
                t.failed_tests,
                t.status,
                t.error_message
            FROM test_runs t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.user_id = %s AND t.project_id = %s
            ORDER BY t.id DESC
        """
        cursor.execute(query, (user_id, project_id))
    elif user_id is not None:
        query = """
            SELECT
                t.id,
                t.user_id,
                t.project_id,
                p.project_name,
                t.created_at,
                t.started_at,
                t.completed_at,
                t.total_tests,
                t.passed_tests,
                t.failed_tests,
                t.status,
                t.error_message
            FROM test_runs t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.user_id = %s
            ORDER BY t.id DESC
        """
        cursor.execute(query, (user_id,))
    else:
        query = """
            SELECT
                t.id,
                t.user_id,
                t.project_id,
                p.project_name,
                t.created_at,
                t.started_at,
                t.completed_at,
                t.total_tests,
                t.passed_tests,
                t.failed_tests,
                t.status,
                t.error_message
            FROM test_runs t
            LEFT JOIN projects p ON t.project_id = p.id
            ORDER BY t.id DESC
        """
        cursor.execute(query)

    runs = cursor.fetchall()

    # ISO format dates for JSON serialization
    for run in runs:
        for dt_field in ("created_at", "started_at", "completed_at"):
            if run.get(dt_field):
                run[dt_field] = run[dt_field].isoformat()

    cursor.close()
    connection.close()

    return runs


def get_test_run_by_id(run_id: int):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            SELECT
                t.id,
                t.user_id,
                t.project_id,
                p.project_name,
                t.created_at,
                t.started_at,
                t.completed_at,
                t.total_tests,
                t.passed_tests,
                t.failed_tests,
                t.status,
                t.error_message
            FROM test_runs t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.id = %s
        """
        cursor.execute(query, (run_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()




def create_user(full_name: str, email: str, password_hash: str, role: str = "user", plan: str = "internal_demo") -> dict:
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            INSERT INTO users (full_name, email, password_hash, role, plan)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (
                full_name.strip(),
                email.lower().strip(),
                password_hash,
                role.strip().lower() if role else "user",
                plan.strip().lower() if plan else "internal_demo"
            )
        )
        user_id = cursor.lastrowid
        connection.commit()

        cursor.execute(
            """
            SELECT id, full_name, email, role, plan, created_at, updated_at
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )
        user = cursor.fetchone()
        return user
    finally:
        cursor.close()
        connection.close()


def get_user_by_email(email: str):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            SELECT id, full_name, email, password_hash, role, plan, created_at, updated_at
            FROM users
            WHERE email = %s
        """
        cursor.execute(query, (email.lower().strip(),))
        user = cursor.fetchone()
        return user
    finally:
        cursor.close()
        connection.close()


def get_user_by_id(user_id: int):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            SELECT id, full_name, email, role, plan, created_at, updated_at
            FROM users
            WHERE id = %s
        """
        cursor.execute(query, (user_id,))
        user = cursor.fetchone()
        return user
    finally:
        cursor.close()
        connection.close()


# ==========================================
# Projects Management Operations
# ==========================================

def _format_project_row(row: Optional[dict], include_secret: bool = False) -> Optional[dict]:
    if not row:
        return None
    formatted = dict(row)
    formatted["has_credentials"] = bool(formatted.get("has_credentials"))
    if not include_secret and "auth_secret_encrypted" in formatted:
        del formatted["auth_secret_encrypted"]
    return formatted


def create_project(
    user_id: int,
    project_name: str,
    base_url: str,
    openapi_url=None,
    description=None,
    auth_type: str = "none",
    auth_header_name: Optional[str] = None,
    auth_secret_encrypted: Optional[str] = None,
    user_plan: Optional[str] = None
) -> dict:
    try:
        from plans import is_quota_enforcement_enabled, get_plan_config
    except ImportError:
        from agent_backend.plans import is_quota_enforcement_enabled, get_plan_config
    from fastapi import HTTPException, status

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        # Atomic lock on user row to serialize simultaneous project creations
        cursor.execute("SELECT id, plan FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user_row = cursor.fetchone()

        if is_quota_enforcement_enabled():
            plan_key = user_plan or (user_row["plan"] if user_row and user_row.get("plan") else "internal_demo")
            plan_cfg = get_plan_config(plan_key)
            max_allowed = plan_cfg.get("max_projects", -1)
            if max_allowed >= 0:
                cursor.execute("SELECT COUNT(*) AS total FROM projects WHERE user_id = %s", (user_id,))
                count = cursor.fetchone()["total"]
                if count >= max_allowed:
                    connection.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Project limit reached ({count}/{max_allowed}) for plan '{plan_cfg['name']}'. "
                            "Upgrade your plan or delete unused projects to create more."
                        )
                    )

        query = """
            INSERT INTO projects (
                user_id, project_name, description, base_url, openapi_url,
                auth_type, auth_header_name, auth_secret_encrypted
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (
                user_id,
                project_name.strip(),
                description.strip() if description else None,
                base_url.strip(),
                openapi_url.strip() if openapi_url else None,
                (auth_type or "none").strip().lower(),
                auth_header_name.strip() if auth_header_name else None,
                auth_secret_encrypted if auth_secret_encrypted else None
            )
        )
        project_id = cursor.lastrowid
        connection.commit()

        cursor.execute(
            """
            SELECT id, user_id, project_name, description, base_url, openapi_url,
                   auth_type, auth_header_name,
                   (auth_secret_encrypted IS NOT NULL AND auth_secret_encrypted != '') AS has_credentials,
                   created_at, updated_at
            FROM projects
            WHERE id = %s
            """,
            (project_id,)
        )
        return _format_project_row(cursor.fetchone())
    finally:
        cursor.close()
        connection.close()


def get_projects_by_user(user_id: int) -> list:
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            SELECT id, user_id, project_name, description, base_url, openapi_url,
                   auth_type, auth_header_name,
                   (auth_secret_encrypted IS NOT NULL AND auth_secret_encrypted != '') AS has_credentials,
                   created_at, updated_at
            FROM projects
            WHERE user_id = %s
            ORDER BY id DESC
        """
        cursor.execute(query, (user_id,))
        rows = cursor.fetchall()
        return [_format_project_row(r) for r in rows]
    finally:
        cursor.close()
        connection.close()


def get_project_by_id(project_id: int, include_secret: bool = False):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        if include_secret:
            query = """
                SELECT id, user_id, project_name, description, base_url, openapi_url,
                       auth_type, auth_header_name, auth_secret_encrypted,
                       (auth_secret_encrypted IS NOT NULL AND auth_secret_encrypted != '') AS has_credentials,
                       created_at, updated_at
                FROM projects
                WHERE id = %s
            """
        else:
            query = """
                SELECT id, user_id, project_name, description, base_url, openapi_url,
                       auth_type, auth_header_name,
                       (auth_secret_encrypted IS NOT NULL AND auth_secret_encrypted != '') AS has_credentials,
                       created_at, updated_at
                FROM projects
                WHERE id = %s
            """
        cursor.execute(query, (project_id,))
        return _format_project_row(cursor.fetchone(), include_secret=include_secret)
    finally:
        cursor.close()
        connection.close()


def update_project(
    project_id: int,
    user_id: int,
    project_name: str,
    base_url: str,
    openapi_url=None,
    description=None,
    auth_type: Optional[str] = None,
    auth_header_name: Optional[str] = None,
    auth_secret_encrypted: Optional[str] = None,
    clear_secret: bool = False
):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, auth_type, auth_header_name, auth_secret_encrypted FROM projects WHERE id = %s AND user_id = %s", (project_id, user_id))
        existing = cursor.fetchone()
        if not existing:
            return None

        # Build dynamic update fields
        set_clauses = [
            "project_name = %s",
            "description = %s",
            "base_url = %s",
            "openapi_url = %s"
        ]
        params = [
            project_name.strip(),
            description.strip() if description else None,
            base_url.strip(),
            openapi_url.strip() if openapi_url else None
        ]

        if auth_type is not None:
            normalized_auth = auth_type.strip().lower()
            set_clauses.append("auth_type = %s")
            params.append(normalized_auth)

            if normalized_auth == "none":
                set_clauses.append("auth_header_name = NULL")
                set_clauses.append("auth_secret_encrypted = NULL")
            else:
                set_clauses.append("auth_header_name = %s")
                params.append(auth_header_name.strip() if auth_header_name else None)

                if auth_secret_encrypted is not None:
                    set_clauses.append("auth_secret_encrypted = %s")
                    params.append(auth_secret_encrypted)
                elif clear_secret:
                    set_clauses.append("auth_secret_encrypted = NULL")
        elif auth_secret_encrypted is not None:
            set_clauses.append("auth_secret_encrypted = %s")
            params.append(auth_secret_encrypted)
        elif clear_secret:
            set_clauses.append("auth_secret_encrypted = NULL")

        params.extend([project_id, user_id])

        query = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = %s AND user_id = %s"
        cursor.execute(query, tuple(params))
        connection.commit()

        cursor.execute(
            """
            SELECT id, user_id, project_name, description, base_url, openapi_url,
                   auth_type, auth_header_name,
                   (auth_secret_encrypted IS NOT NULL AND auth_secret_encrypted != '') AS has_credentials,
                   created_at, updated_at
            FROM projects
            WHERE id = %s
            """,
            (project_id,)
        )
        return _format_project_row(cursor.fetchone())
    finally:
        cursor.close()
        connection.close()


def delete_project(project_id: int, user_id: int) -> bool:
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM projects WHERE id = %s AND user_id = %s", (project_id, user_id))
        if not cursor.fetchone():
            return False

        cursor.execute("DELETE FROM projects WHERE id = %s AND user_id = %s", (project_id, user_id))
        connection.commit()
        return True
    finally:
        cursor.close()
        connection.close()


def get_user_test_run_by_id(run_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single test run by run_id, strictly scoped to authenticated user_id.
    Guarantees tenant isolation: returns None if the run does not exist or belongs
    to another tenant. Computes pass_rate dynamically.
    """
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = """
            SELECT
                t.id,
                t.user_id,
                t.project_id,
                p.project_name,
                t.created_at,
                t.started_at,
                t.completed_at,
                t.base_url,
                t.openapi_url,
                t.total_tests,
                t.passed_tests,
                t.failed_tests,
                t.error_message,
                t.status,
                t.estimated_tests,
                t.heartbeat_at,
                t.reservation_expires_at,
                t.idempotency_key,
                t.payload_hash,
                t.worker_id
            FROM test_runs t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.id = %s AND t.user_id = %s
        """
        cursor.execute(query, (run_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None

        total = row.get("total_tests") or 0
        passed = row.get("passed_tests") or 0
        row["pass_rate"] = round((passed / total) * 100, 2) if total > 0 else 0.0

        # ISO format dates if present
        for dt_field in ("created_at", "started_at", "completed_at", "heartbeat_at", "reservation_expires_at"):
            if row.get(dt_field):
                row[dt_field] = row[dt_field].isoformat()

        return row
    finally:
        cursor.close()
        connection.close()


def release_worker_slot(run_id: int, worker_id: Optional[str] = None) -> bool:
    """
    Release any worker slot currently occupied or leased by run_id in worker_slots.
    If worker_id is provided, only releases if worker_id matches, preventing stale workers
    from clearing slots reassigned to newer workers.
    Safe for idempotent calls.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        if worker_id is not None:
            cursor.execute(
                """
                UPDATE worker_slots
                SET run_id = NULL, worker_id = NULL, leased_until = NULL
                WHERE run_id = %s AND worker_id = %s
                """,
                (run_id, worker_id)
            )
        else:
            cursor.execute(
                """
                UPDATE worker_slots
                SET run_id = NULL, worker_id = NULL, leased_until = NULL
                WHERE run_id = %s
                """,
                (run_id,)
            )
        connection.commit()
        try:
            return bool(cursor.rowcount > 0)
        except TypeError:
            return True
    finally:
        cursor.close()
        connection.close()


def claim_next_queued_job(
    worker_id: str,
    max_concurrent_running: int = 5
) -> Optional[Dict[str, Any]]:
    """
    Atomically claim the oldest eligible queued job in FIFO order using a transaction
    and SELECT ... FOR UPDATE SKIP LOCKED on both worker_slots and test_runs.

    - Locks an available or expired slot from worker_slots where slot_id <= max_concurrent_running.
    - If no slot is free, returns None immediately without lock contention.
    - Locks and transitions status of oldest queued job from 'queued' to 'running'.
    - Updates worker_slots and test_runs with 5-minute lease and timestamps.
    - Commits transaction atomically and returns the claimed job dictionary (including slot_id).
    - Automatically rolls back on empty queue or error.
    """
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        # 1. Acquire an available worker slot under lock
        cursor.execute(
            """
            SELECT slot_id FROM worker_slots
            WHERE (run_id IS NULL OR leased_until < UTC_TIMESTAMP())
              AND slot_id <= %s
            ORDER BY slot_id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (max_concurrent_running,)
        )
        slot = cursor.fetchone()
        if not slot:
            connection.rollback()
            return None

        slot_id = slot["slot_id"]

        # 2. Select oldest queued job using SKIP LOCKED to prevent lock contention
        cursor.execute(
            """
            SELECT
                id, user_id, project_id, created_at, base_url, openapi_url,
                idempotency_key, estimated_tests, payload_hash
            FROM test_runs
            WHERE status = 'queued'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        job = cursor.fetchone()
        if not job:
            connection.rollback()
            return None

        job_id = job["id"]

        # 3. Reserve the slot for this run
        cursor.execute(
            """
            UPDATE worker_slots
            SET run_id = %s,
                worker_id = %s,
                leased_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
            WHERE slot_id = %s
            """,
            (job_id, worker_id, slot_id)
        )

        # 4. Transition job from 'queued' to 'running' atomically
        cursor.execute(
            """
            UPDATE test_runs
            SET status = 'running',
                worker_id = %s,
                started_at = UTC_TIMESTAMP(),
                heartbeat_at = UTC_TIMESTAMP(),
                reservation_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, job_id)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        connection.commit()

        job["status"] = "running"
        job["worker_id"] = worker_id
        job["slot_id"] = slot_id
        return job
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def extend_worker_slot_lease(run_id: int, worker_id: Optional[str] = None, minutes: int = 5) -> bool:
    """
    Extend the leased_until timestamp for a running job's slot in worker_slots.
    If worker_id is provided, verifies that the slot is still assigned to worker_id.
    Safe for idempotent calls.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        if worker_id is not None:
            cursor.execute(
                """
                UPDATE worker_slots
                SET leased_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s MINUTE)
                WHERE run_id = %s AND worker_id = %s
                """,
                (minutes, run_id, worker_id)
            )
        else:
            cursor.execute(
                """
                UPDATE worker_slots
                SET leased_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s MINUTE)
                WHERE run_id = %s
                """,
                (minutes, run_id)
            )
        connection.commit()
        try:
            return bool(cursor.rowcount > 0)
        except TypeError:
            return True
    finally:
        cursor.close()
        connection.close()


def reconcile_orphan_worker_slots() -> int:
    """
    Clear slots in worker_slots held by test runs that are no longer active
    (completed, failed, or cancelled) or whose lease has expired.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE worker_slots ws
            JOIN test_runs tr ON ws.run_id = tr.id
            SET ws.run_id = NULL, ws.worker_id = NULL, ws.leased_until = NULL
            WHERE tr.status IN ('completed', 'failed', 'cancelled')
               OR ws.leased_until < UTC_TIMESTAMP()
            """
        )
        connection.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        connection.close()



