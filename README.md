# AI API Testing Agent

An AI-powered API testing platform that analyzes OpenAPI specifications, generates test cases, executes HTTP requests, validates responses, and helps identify potential API defects.

## Overview

Testing APIs manually can be time-consuming, especially when covering edge cases, invalid inputs, and boundary conditions.

The **AI API Testing Agent** combines rule-based testing with AI-generated test cases to automate much of this workflow. It uses an OpenAPI specification to understand endpoints and their request/response contracts, then generates and executes tests against a target API.

## Key Features

- **OpenAPI Parsing:** Extracts API endpoints, parameters, request schemas, and documented responses.
- **Rule-Based Test Generation:** Creates positive and negative tests from API schemas and validation rules.
- **AI-Powered Test Generation:** Uses Gemini to generate additional edge cases.
- **Automated Test Execution:** Sends HTTP requests to the target API and records actual responses.
- **Response Validation:** Compares actual responses with expected behavior.
- **Expectation Confidence:** Flags uncertain AI-generated expectations for manual review to reduce false-positive bug reports.
- **Unicode and Edge-Case Testing:** Supports testing unusual strings, boundary values, and varied input formats.
- **Test Result Storage:** Saves execution results in the configured database.
- **Regression Testing:** Includes automated tests for key generator and validator behaviors.

## Architecture

```text
                 OpenAPI Specification
                          |
                          v
                   OpenAPI Parser
                          |
                          v
                Endpoint and Schema Data
                          |
                +---------+---------+
                |                   |
                v                   v
        Rule-Based Generator   AI Test Generator
                |                   |
                +---------+---------+
                          |
                          v
                   Test Collection
                          |
                          v
                    Test Executor
                          |
                          v
                     Target API
                          |
                          v
                  Response Validator
                          |
                +---------+---------+
                |                   |
                v                   v
          Test Results       Potential Defects
                |             / Manual Review
                v
             Database
                |
                v
           Web Dashboard
```

## Technology Stack

| Component | Technology |
|---|---|
| Backend API | Python, FastAPI |
| AI test generation | Google Gemini API |
| API specification | OpenAPI |
| Target API | FastAPI |
| Frontend | React, Vite |
| HTTP execution | Python HTTP client |
| Testing | pytest |
| Database | Project-configured database |

## Project Structure

```text
AI_API_Testing_Agent/
├── agent_backend/
│   ├── app.py
│   ├── database.py
│   ├── engine/
│   │   ├── ai_generator/
│   │   ├── ai_analyzer/
│   │   ├── parser/
│   │   └── test_generator/
│   └── tests/
├── dashboard/
│   └── src/
├── target_api/
│   └── main.py
├── tests/
│   └── test_regression_suite.py
├── pytest.ini
└── README.md
```

## Getting Started

### Prerequisites

- Python installed
- Node.js and npm installed
- Git
- A Gemini API key for AI-powered test generation
- Database configuration required by the backend

### 1. Clone the repository

```bash
git clone https://github.com/ankitpyj/AI_API_Testing_Agent-.git
cd AI_API_Testing_Agent-
```

### 2. Set up the Python environment

From the project root in PowerShell:

```powershell
python -m venv agent_backend\venv
.\agent_backend\venv\Scripts\Activate.ps1
pip install -r agent_backend\requirements.txt
```

If the requirements file is located elsewhere in your repository, use its actual path.

### 3. Configure environment variables

Create a local `.env` file in the location expected by the backend. Add the required environment variables, such as the Gemini API key and database settings, based on your project configuration.

**Never commit API keys, passwords, or other secrets to GitHub.**

### 4. Start the target API

In a separate terminal:

```powershell
cd target_api
python -m uvicorn main:app --reload --port 8000
```

The target API will be available at:

`http://127.0.0.1:8000`

### 5. Start the agent backend

From the project root, in another terminal:

```powershell
.\agent_backend\venv\Scripts\Activate.ps1
python -m uvicorn agent_backend.app:app --reload --port 5000
```

### 6. Start the dashboard

In another terminal:

```powershell
cd dashboard
npm install
npm run dev
```

Open the local URL printed by Vite in your terminal.

> Ensure the dashboard's backend URL matches the port used by the backend. Configure the target API URL and environment variables according to your local setup.

## Running Tests

From the project root:

```powershell
.\agent_backend\venv\Scripts\python.exe -m pytest -v
```

The latest reported verification results during development were:

- **Automated test suite:** 99 passed, 0 failed
- **Live end-to-end run:** 44 passed, 0 failed
- **Latest reported run ID:** 78

These results represent a particular development run and are not a guarantee that every API or environment will produce the same outcome.

## How It Works

1. The agent loads an OpenAPI specification.
2. The parser extracts endpoints, schemas, and documented response codes.
3. The rule-based generator creates tests from schema constraints.
4. Gemini generates additional edge-case tests.
5. The executor sends requests to the configured target API.
6. The validator evaluates the responses and classifies mismatches.
7. Uncertain expectations are flagged for review instead of automatically being treated as confirmed API defects.
8. Test results are stored and made available to the dashboard.

## Important Design Principle

**An unexpected response is not automatically a confirmed API bug.**

The agent considers documented API behavior and the confidence of each test expectation. When an AI-generated expectation is uncertain, the result should be reviewed before treating it as a confirmed defect.

## Future Improvements

- Support more API authentication methods.
- Improve test coverage across additional OpenAPI features.
- Add more target API integrations and environment configurations.
- Enhance bug report generation and export options.
- Add CI/CD integration for automated regression testing.
- Improve deployment and configuration documentation.

## Author

**Ankit Nagar**

GitHub: [@ankitpyj](https://github.com/ankitpyj)


No license has been specified yet. Add a license if you want to define the terms under which others may use, modify, or distribute this project.
