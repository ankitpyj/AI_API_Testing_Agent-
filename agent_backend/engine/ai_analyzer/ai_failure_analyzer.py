import os
import json
import logging

from openai import OpenAI
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# Use GEMINI_MODEL env var so this can be overridden in Render without a code
# change.  The default is a real, low-cost model available via the Gemini
# OpenAI-compatibility endpoint.
#
# WARNING: "gemini-3.5-flash-lite" does NOT exist — using it causes every API
# call to fail with a model-not-found error, producing analyzer_failed=True on
# every result.  Always verify the model name at ai.google.dev/gemini-api/docs.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-8b")

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


def analyze_failure(result):
    """
    Analyze a failed API test using an LLM.

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

    prompt = f"""
You are an expert software tester.

Analyze the following failed API test.

Test Result:

{json.dumps(result, indent=2)}

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


    try:

        response = client.chat.completions.create(

            model=GEMINI_MODEL,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.2,

            max_tokens=500,

            timeout=120,
            response_format={"type": "json_object"}
        )


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
