import os
import json

from openai import OpenAI
from dotenv import load_dotenv


# Load environment variables
load_dotenv()


# # Create NVIDIA client
# client = OpenAI(
#     api_key=os.getenv("NVIDIA_API_KEY"),
#     base_url="https://integrate.api.nvidia.com/v1"
# )
# Gemini client
client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=60.0,
    max_retries=0
)

GEMINI_MODEL = "gemini-3.5-flash-lite"


def analyze_failure(result):
    """
    Analyze a failed API test using an LLM.
    """

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

            print(
                "[AI Analyzer] Invalid JSON received from Gemini."
            )

            print(
                "[AI Analyzer] Raw response:"
            )

            print(response_text)


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

        print(
            f"[AI Analyzer] Error: {e}"
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