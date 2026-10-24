
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parser.openapi_parser import (
    load_openapi,
    extract_endpoints
)

from ai_generator.ai_test_generator import (
    generate_ai_tests
)

from test_generator.test_executor import (
    execute_test
)

from test_generator.response_validator import (
    validate_response
)


# Load OpenAPI
openapi_data = load_openapi(
    "http://127.0.0.1:8000/openapi.json"
)


# Extract endpoints
endpoints = extract_endpoints(
    openapi_data
)


# Find POST /users
api_info = None

for endpoint in endpoints:

    if (
        endpoint["path"] == "/users"
        and endpoint["method"] == "POST"
    ):
        api_info = endpoint
        break


if api_info is None:
    print("POST /users not found")
    exit()


# Generate AI tests
ai_tests = generate_ai_tests(
    api_info
)


print("\nAI TEST EXECUTION")
print("=" * 70)


passed = 0
failed = 0


for index, test in enumerate(
    ai_tests,
    start=1
):

    print(f"\nAI-TC-{index}")
    print(
        f"Description: "
        f"{test['description']}"
    )

    # Add test_id to test
    test['test_id'] = f"AI-TC-{index}"

    # Execute test
    result = execute_test(test)

    # Validate response
    validated_result = validate_response(
        result
    )

    print(
        f"Status: "
        f"{validated_result['status']}"
    )

    print(
        f"Expected: "
        f"{validated_result['expected_status']}"
    )

    print(
        f"Actual: "
        f"{validated_result['actual_status']}"
    )

    if validated_result["status"] == "PASS":
        passed += 1
    else:
        failed += 1

        print(
            f"Failure Reason: "
            f"{validated_result['failure_reason']}"
        )


print("\n")
print("=" * 70)
print("AI TEST SUMMARY")
print("=" * 70)

print(f"Total: {len(ai_tests)}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")