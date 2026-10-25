import json

from database import get_db_connection


def create_test_run(total_tests, passed_tests, failed_tests):
    connection = get_db_connection()
    cursor = connection.cursor()

    query = """
        INSERT INTO test_runs
        (total_tests, passed_tests, failed_tests)
        VALUES (%s, %s, %s)
    """

    cursor.execute(
        query,
        (
            total_tests,
            passed_tests,
            failed_tests
        )
    )

    run_id = cursor.lastrowid

    connection.commit()

    cursor.close()
    connection.close()

    return run_id


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

    expected_body = (
        result.get("expected_schema")
        if result.get("expected_schema") is not None
        else (
            expected.get("response_schema")
            or expected.get("schema")
            or expected.get("body")
            or {}
        )
    )

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
            json.dumps(result.get("request", {})),
            json.dumps(actual_body),
            result.get("failure_reason")
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
            bug_report.get("summary"),
            bug_report.get("possible_cause"),
            bug_report.get("recommendation"),
            bug_report.get("status", "Open")
        )
    )

    connection.commit()

    cursor.close()
    connection.close()
    
    
def get_test_runs():

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            id,
            started_at,
            total_tests,
            passed_tests,
            failed_tests
        FROM test_runs
        ORDER BY id DESC
    """

    cursor.execute(query)

    runs = cursor.fetchall()

    cursor.close()
    connection.close()

    return runs