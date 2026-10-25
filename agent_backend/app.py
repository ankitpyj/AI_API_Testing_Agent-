import sys
import os
from pathlib import Path
from agent_backend.database import get_db_connection
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
import json
# Add parent directory to path to import sibling modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_backend.engine.test_generator.test_executor import run_all_tests

from agent_backend.db_operations import (
    create_test_run,
    save_test_result,
    save_bug_report,
    get_test_runs
)

class RunTestsRequest(BaseModel):
    base_url: str = "http://127.0.0.1:8000"
    openapi_url: Optional[str] = None

app = FastAPI(
    title="AI API Testing Agent",
    description="Backend for automated API testing",
    version="1.0.0"
)




FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173"
).rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "AI Testing Agent Backend is running"
    }


@app.post("/run-tests")
def run_tests(config: Optional[RunTestsRequest] = None):
    base_url = (
        config.base_url
        if config
        else "http://127.0.0.1:8000"
    )

    openapi_url = (
        config.openapi_url
        if config
        else None
    )

    result = run_all_tests(
        base_url=base_url,
        openapi_url=openapi_url
    )

    return {
        "status": "success",
        "data": result
    }
    
@app.get("/test-runs")
def get_test_runs_endpoint():

    runs = get_test_runs()

    return {
        "status": "success",
        "data": runs
    }
    
@app.get("/test-runs/{run_id}/results")
def get_test_results(run_id: int):

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            id,
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
        FROM test_results
        WHERE run_id = %s
        ORDER BY id
        """,
        (run_id,)
    )

    results = cursor.fetchall()

    cursor.close()
    connection.close()

    return {
        "status": "success",
        "data": results
    }
    
@app.get("/test-runs/{run_id}/bugs")
def get_bug_reports(run_id: int):

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            id,
            run_id,
            test_id,
            bug_id,
            endpoint,
            severity,
            summary,
            possible_cause,
            recommendation,
            status
        FROM bug_reports
        WHERE run_id = %s
        ORDER BY id
        """,
        (run_id,)
    )

    bugs = cursor.fetchall()

    cursor.close()
    connection.close()

    return {
        "status": "success",
        "data": bugs
    }