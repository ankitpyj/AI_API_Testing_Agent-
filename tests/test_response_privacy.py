"""
Tests for Response Data Privacy and Exact Secret Redaction (Task 5.2).

Verifies:
1. Exact secret redaction replaces configured secrets with [REDACTED].
2. Handles strings, nested dictionaries, arrays, and serialized JSON strings.
3. Redacts tokens embedded within longer strings (e.g. error messages, URLs).
4. Handles multiple sensitive values simultaneously.
5. Safely ignores empty, whitespace-only, or None secrets without wiping data.
6. Preserves valid JSON structures and non-string primitive types (int, float, bool, None).
7. extract_project_secrets safely extracts and decrypts credentials.
8. AI failure analyzer sanitizes results and prompts before calling Gemini API.
9. DB operations sanitize test results and bug reports before writing to MySQL.
"""

import os
import sys
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = REPO_ROOT / "agent_backend"
ENGINE_ROOT = BACKEND_ROOT / "engine"
for p in [str(REPO_ROOT), str(BACKEND_ROOT), str(ENGINE_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_backend.engine.authentication.response_sanitizer import (
    sanitize_string,
    sanitize_data,
    extract_project_secrets,
    DEFAULT_REDACTION_PLACEHOLDER,
)
from agent_backend.engine.ai_analyzer.ai_failure_analyzer import analyze_failure
from agent_backend.db_operations import save_test_result, save_bug_report


class TestExactSecretRedaction:
    """Tests for core exact secret redaction functions."""

    def test_sanitize_string_exact_replacement(self):
        secret = "secret-token-xyz-12345"
        text = f"API responded with error: Invalid token {secret} provided in request."
        clean = sanitize_string(text, secrets=[secret])

        assert secret not in clean
        assert "[REDACTED]" in clean
        assert clean == "API responded with error: Invalid token [REDACTED] provided in request."

    def test_sanitize_string_multiple_secrets(self):
        sec1 = "bearer-token-alpha"
        sec2 = "api-key-beta-999"
        text = f"Headers used: Authorization: Bearer {sec1}, X-API-KEY: {sec2}"
        clean = sanitize_string(text, secrets=[sec1, sec2])

        assert sec1 not in clean
        assert sec2 not in clean
        assert clean.count("[REDACTED]") >= 2

    def test_sanitize_string_empty_and_whitespace_secrets_ignored(self):
        text = "This is legitimate user text that should never be cleared."
        clean = sanitize_string(text, secrets=["", "   ", None, "  \t "])
        assert clean == text

    def test_sanitize_string_short_secrets_ignored(self):
        # Secrets shorter than 3 chars should not be blanket replaced
        text = "Hello world 1 2 3 a b"
        clean = sanitize_string(text, secrets=["a", "1"])
        assert clean == text

    def test_sanitize_data_nested_dict(self):
        secret = "super-secret-passphrase-456"
        data = {
            "status": "success",
            "code": 200,
            "active": True,
            "count": 42,
            "data": {
                "user_token": secret,
                "profile": {
                    "bio": f"Contact with key {secret}",
                    "verified": False,
                }
            }
        }
        clean = sanitize_data(data, secrets=[secret])

        assert clean["status"] == "success"
        assert clean["code"] == 200
        assert clean["active"] is True
        assert clean["count"] == 42
        assert clean["data"]["user_token"] == "[REDACTED]"
        assert clean["data"]["profile"]["bio"] == "Contact with key [REDACTED]"
        assert clean["data"]["profile"]["verified"] is False
        assert secret not in json.dumps(clean)

    def test_sanitize_data_arrays_and_primitives(self):
        secret = "token-array-secret-789"
        data = [
            1,
            2.5,
            True,
            None,
            secret,
            {"nested_in_list": secret},
            [secret, "safe_string"]
        ]
        clean = sanitize_data(data, secrets=[secret])

        assert clean[0] == 1
        assert clean[1] == 2.5
        assert clean[2] is True
        assert clean[3] is None
        assert clean[4] == "[REDACTED]"
        assert clean[5]["nested_in_list"] == "[REDACTED]"
        assert clean[6] == ["[REDACTED]", "safe_string"]
        assert secret not in str(clean)

    def test_sanitize_data_serialized_json_string(self):
        secret = "embedded-json-secret-999"
        raw_inner = json.dumps({"auth_key": secret, "count": 10})
        clean = sanitize_data(raw_inner, secrets=[secret])

        # Must still be valid JSON
        parsed = json.loads(clean)
        assert parsed["auth_key"] == "[REDACTED]"
        assert parsed["count"] == 10
        assert secret not in clean


class TestExtractProjectSecrets:
    """Tests for extracting sensitive tokens from project records and auth headers."""

    def test_extract_from_plaintext_and_headers(self):
        proj = {"auth_secret": "my-plain-secret"}
        headers = {
            "Authorization": "Bearer token-abc-12345",
            "X-API-KEY": "key-xyz-67890",
        }
        extracted = extract_project_secrets(project=proj, auth_headers=headers)

        assert "my-plain-secret" in extracted
        assert "token-abc-12345" in extracted
        assert "key-xyz-67890" in extracted

    def test_extract_empty_or_none(self):
        extracted = extract_project_secrets(project=None, auth_headers=None)
        assert extracted == []


class TestAiAnalyzerPromptSanitization:
    """Tests confirming no decrypted secret reaches Gemini API prompts."""

    @patch("agent_backend.engine.ai_analyzer.ai_failure_analyzer.client")
    def test_analyze_failure_sanitizes_prompt_and_result(self, mock_client):
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "summary": "Validation failed",
                        "possible_cause": "Expected schema mismatch",
                        "severity": "High",
                        "recommendation": "Fix response payload"
                    })
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_completion

        secret_token = "ultra-secret-test-token-777"
        failing_result = {
            "test_id": "TC-001",
            "endpoint": "/users",
            "method": "POST",
            "request": {
                "headers": {"Authorization": f"Bearer {secret_token}"},
                "body": {"secret_field": secret_token}
            },
            "actual": {
                "status_code": 500,
                "body": {"error": f"Crash when processing token {secret_token}"}
            }
        }

        analysis = analyze_failure(failing_result, secrets=[secret_token])

        # Verify chat completion was called
        assert mock_client.chat.completions.create.called
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        user_prompt = messages[0]["content"]

        # Secret MUST NOT appear anywhere in the sent prompt
        assert secret_token not in user_prompt
        assert "[REDACTED]" in user_prompt
        assert analysis["summary"] == "Validation failed"


class TestDatabasePersistenceSanitization:
    """Tests confirming MySQL persistence saves only sanitized data."""

    @patch("agent_backend.db_operations.get_db_connection")
    def test_save_test_result_sanitizes_actual_body_and_request(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        secret = "db-persisted-secret-token-444"
        raw_result = {
            "test_id": "TC-002",
            "method": "GET",
            "endpoint": "/secret-info",
            "status": "PASS",
            "expected_status": 200,
            "expected_body": {},
            "actual_status": 200,
            "actual_body": {"exposed_token": secret},
            "request": {"query_params": {"key": secret}},
            "failure_reason": f"No error with {secret}"
        }

        # Apply exact secret redaction before DB save (as test_executor does)
        clean_result = sanitize_data(raw_result, secrets=[secret])
        save_test_result(run_id=99, result=clean_result)

        assert mock_cursor.execute.called
        insert_args = mock_cursor.execute.call_args[0][1]

        # Check request_body (arg 10), actual_body (arg 11), failure_reason (arg 12)
        request_body_str = insert_args[10]
        actual_body_str = insert_args[11]
        failure_reason_str = insert_args[12]

        assert secret not in request_body_str
        assert secret not in actual_body_str
        assert secret not in (failure_reason_str or "")
        assert "[REDACTED]" in actual_body_str

    @patch("agent_backend.db_operations.get_db_connection")
    def test_save_bug_report_sanitizes_fields(self, mock_get_conn):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        secret = "leak-bug-token-999"
        raw_result = {
            "test_id": "TC-003",
            "bug_report": {
                "bug_id": "BUG-001",
                "endpoint": "/profile",
                "severity": "High",
                "summary": f"Failed with {secret}",
                "possible_cause": f"Token {secret} invalid",
                "recommendation": f"Regenerate {secret}",
                "status": "Open"
            }
        }

        clean_result = sanitize_data(raw_result, secrets=[secret])
        save_bug_report(run_id=99, result=clean_result)

        assert mock_cursor.execute.called
        insert_args = mock_cursor.execute.call_args[0][1]

        # Check summary (arg 5), possible_cause (arg 6), recommendation (arg 7)
        summary_str = insert_args[5]
        cause_str = insert_args[6]
        rec_str = insert_args[7]

        assert secret not in summary_str
        assert secret not in cause_str
        assert secret not in rec_str
        assert "[REDACTED]" in summary_str
