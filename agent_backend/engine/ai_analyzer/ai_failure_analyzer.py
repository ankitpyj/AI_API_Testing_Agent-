import os
import json
import logging

from openai import OpenAI
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Import common retry helper
try:
    from engine.common.gemini_retry import execute_with_retry
except ImportError:
    try:
        from common.gemini_retry import execute_with_retry
    except ImportError:
        from agent_backend.engine.common.gemini_retry import execute_with_retry

try:
    from engine.authentication.project_auth import sanitize_text
except ImportError:
    try:
        from agent_backend.engine.authentication.project_auth import sanitize_text
    except ImportError:
        sanitize_text = lambda t, *args: t

try:
    from engine.authentication.response_sanitizer import sanitize_data, sanitize_string
except ImportError:
    try:
        from agent_backend.engine.authentication.response_sanitizer import sanitize_data, sanitize_string
    except ImportError:
        sanitize_data = lambda d, *args, **kwargs: d
        sanitize_string = lambda s, *args, **kwargs: s

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# Use GEMINI_MODEL env var so this can be overridden in Render without a code
# change. Default is 'gemini-flash-lite-latest', which is Google's active, supported
# lightweight model alias that reliably handles JSON generation.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------
# Defer key validation so a missing GEMINI_API_KEY does not raise at import
# time and crash the entire test pipeline.  When the key is absent, every call
# to analyze_failure() returns analyzer_failed=True gracefully.

_api_key = os.getenv("GEMINI_API_KEY")

if not _api_key:
    logger.warning(
        "[AI Analyzer] GEMINI_API_KEY is not set. "
        "AI failure analysis will be unavailable until the key is configured."
    )

# Build client regardless — if the key is missing the first API call will fail
# and be caught by the exception handler inside analyze_failure().
try:
    client = OpenAI(
        api_key=_api_key or "placeholder-key-not-set",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=60.0,
        max_retries=0,
    )
except Exception as _client_init_error:
    logger.warning(
        "[AI Analyzer] Failed to initialise Gemini client: %s",
        _client_init_error,
    )
    client = None


def analyze_failure(result, secrets=None, user_id=None, run_id=None):
    """
    Analyze a failed API test using an LLM.

    Sanitizes result data and prompts against configured secrets before sending
    to the Gemini API to prevent credential leakage.

    Returns a dict with the analysis on success, or a dict with
    analyzer_failed=True when analysis could not be completed.
    The test PASS/FAIL result is always preserved regardless.
    """

    # Guard: if the client could not be initialised, fail gracefully.
    if client is None:
        logger.warning(
            "[AI Analyzer] Client is not initialised (likely missing "
            "GEMINI_API_KEY or failed client setup). Skipping analysis."
        )
        return {
            "analyzer_failed": True,
            "summary": (
                "The API test failed and AI analysis could not be completed."
            ),
            "possible_cause": (
                "The AI analyzer client is not initialised. "
                "Ensure GEMINI_API_KEY is set and the client can connect to "
                "the Gemini API."
            ),
            "severity": "Medium",
            "recommendation": (
                "Set the GEMINI_API_KEY environment variable and verify that "
                "GEMINI_MODEL is a valid model name "
                "(e.g. gemini-1.5-flash-8b)."
            ),
        }

    # Data privacy: sanitize the test result payload before including it in the prompt
    clean_result = sanitize_data(result, secrets=secrets)

    prompt = f"""
You are an expert software tester.

Analyze the following failed API test.

Test Result:

{json.dumps(clean_result, indent=2)}

Explain the failure using ONLY evidence present
in the test result.

Important rules:

1. Clearly distinguish facts from hypotheses.

2. Do NOT assume an internal service, database,
dependency, or business rule failed unless the test result provides evidence for it.

3. If the exact root cause cannot be determined,
explicitly say that it cannot be determined.

4. A possible cause must be phrased as a hypothesis.

5. Do not recommend changing the HTTP status code
unless the test evidence or API contract supports it.

Return ONLY valid JSON using this format:

{{
    "summary": "Short explanation of the failure",
    "possible_cause": "Likely reason for the failure",
    "severity": "Low | Medium | High | Critical",
    "recommendation": "What should the developer investigate or fix"
}}

Do not invent information that is not supported
by the test result.

Keep each JSON value short.
"""

    clean_prompt = sanitize_string(prompt, secrets=secrets)
    clean_prompt = sanitize_text(clean_prompt)

    ai_log_id = None
    if user_id is not None:
        try:
            try:
                from usage_service import reserve_ai_operation, is_quota_enforcement_enabled
            except ImportError:
                from agent_backend.usage_service import reserve_ai_operation, is_quota_enforcement_enabled
            ai_log_id = reserve_ai_operation(
                user_id=user_id,
                run_id=run_id,
                call_type="analysis",
                model=GEMINI_MODEL
            )
            if ai_log_id is None and is_quota_enforcement_enabled():
                logger.info("[AI Analyzer] Monthly AI operation limit reached. Falling back to deterministic rule-based analysis.")
                return {
                    "analyzer_failed": False,
                    "is_ai": False,
                    "summary": f"API defect on {result.get('endpoint', '')}: expected status {result.get('expected_status')}, received {result.get('actual_status')}",
                    "possible_cause": result.get("failure_reason", "Expected HTTP status did not match actual response."),
                    "severity": "Medium",
                    "recommendation": "Review endpoint logic and response schema definitions in the OpenAPI documentation."
                }
        except Exception as res_err:
            logger.debug("[AI Analyzer] AI reservation check bypassed: %s", res_err)

    try:
        def _call_gemini():
            return client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": clean_prompt
                    }
                ],
                temperature=0.2,
                max_tokens=1000,
                timeout=120,
                response_format={"type": "json_object"}
            )

        response = execute_with_retry(
            _call_gemini,
            max_retries=3,
            base_delay=2.0,
            caller_name="AI Analyzer",
        )

        if ai_log_id is not None:
            try:
                try:
                    from usage_service import complete_ai_operation
                except ImportError:
                    from agent_backend.usage_service import complete_ai_operation
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "prompt_tokens", 0) or 0
                out_tok = getattr(usage, "completion_tokens", 0) or 0
                tot_tok = getattr(usage, "total_tokens", 0) or (in_tok + out_tok)
                complete_ai_operation(ai_log_id, in_tok, out_tok, tot_tok)
            except Exception as log_err:
                logger.warning("[AI Analyzer] Failed to complete AI usage: %s", log_err)
        elif user_id is not None:
            try:
                try:
                    from db_operations import log_ai_usage
                except ImportError:
                    from agent_backend.db_operations import log_ai_usage
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "prompt_tokens", None) if usage else None
                out_tok = getattr(usage, "completion_tokens", None) if usage else None
                tot_tok = getattr(usage, "total_tokens", None) if usage else None
                log_ai_usage(
                    user_id=user_id,
                    run_id=run_id,
                    call_type="analysis",
                    provider="gemini",
                    model=GEMINI_MODEL,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    total_tokens=tot_tok,
                    status="success"
                )
            except Exception as log_err:
                logger.warning("[AI Analyzer] Failed to log AI usage: %s", log_err)

        response_text = (
            response.choices[0]
            .message.content
            .strip()
        )


        # Remove markdown code fences
        if response_text.startswith("```"):

            response_text = response_text.replace(
                "```json",
                ""
            ).replace(
                "```",
                ""
            ).strip()


        # Convert JSON to Python dictionary
        try:

            analysis = json.loads(response_text)

            return analysis

        except json.JSONDecodeError:

            logger.warning(
                "[AI Analyzer] Invalid JSON received from Gemini "
                "(model=%s). Raw response length: %d chars.",
                GEMINI_MODEL,
                len(response_text),
            )

            # Safe fallback — mark analyzer_failed so callers can skip bug report
            return {
                "analyzer_failed": True,
                "summary": (
                    "The API test failed, but the AI analyzer "
                    "returned an invalid response."
                ),

                "possible_cause": (
                    "The exact root cause could not be determined "
                    "from the AI analysis."
                ),

                "severity": "Medium",

                "recommendation": (
                    "Review the test result and API response manually."
                )
            }


    except Exception as e:
        if ai_log_id is not None:
            try:
                try:
                    from usage_service import fail_ai_operation
                except ImportError:
                    from agent_backend.usage_service import fail_ai_operation
                fail_ai_operation(ai_log_id)
            except Exception:
                pass
        elif user_id is not None:
            try:
                try:
                    from db_operations import log_ai_usage
                except ImportError:
                    from agent_backend.db_operations import log_ai_usage
                log_ai_usage(
                    user_id=user_id,
                    run_id=run_id,
                    call_type="analysis",
                    provider="gemini",
                    model=GEMINI_MODEL,
                    status="failed"
                )
            except Exception:
                pass

        # Log the error type and message but NOT the full API response, key,
        # or any authorisation headers — only safe diagnostic information.
        logger.error(
            "[AI Analyzer] API call failed (model=%s, error_type=%s): %s",
            GEMINI_MODEL,
            type(e).__name__,
            str(e),
        )

        # Prevent the complete test pipeline from crashing.
        # analyzer_failed=True signals that the PASS/FAIL outcome of the test
        # is still valid, but AI analysis was unavailable — do NOT generate a
        # bug report purely because the analyzer failed.
        return {
            "analyzer_failed": True,
            "summary": (
                "The API test failed and AI analysis "
                "could not be completed."
            ),

            "possible_cause": (
                "The exact root cause could not be determined "
                "because the AI analyzer was unavailable."
            ),

            "severity": "Medium",

            "recommendation": (
                "Review the failed test result manually "
                "and investigate the API behavior."
            )
        }
