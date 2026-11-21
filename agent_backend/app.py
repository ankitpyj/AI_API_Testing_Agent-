import sys
import os
import json
import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from agent_backend.database import get_db_connection
from fastapi import FastAPI, Depends, HTTPException, status, Header, Request, Response
from pydantic import BaseModel
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from agent_backend.logger import logger, request_id_ctx
except ImportError:
    from logger import logger, request_id_ctx
# Add parent directory to path to import sibling modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_backend.engine.test_generator.test_executor import run_all_tests

try:
    from agent_backend import db_operations
except ImportError:
    import db_operations

from agent_backend.db_operations import (
    create_test_run,
    save_test_result,
    save_bug_report,
    get_test_runs,
    get_test_run_by_id,
    get_user_test_run_by_id
)


try:
    from agent_backend.auth import get_current_user
except ImportError:
    from auth import get_current_user

try:
    from agent_backend.routes.auth import router as auth_router
except ImportError:
    from routes.auth import router as auth_router

try:
    from agent_backend.routes.projects import router as projects_router
except ImportError:
    from routes.projects import router as projects_router

try:
    from agent_backend.routes.analytics import router as analytics_router
except ImportError:
    from routes.analytics import router as analytics_router

try:
    from agent_backend.routes.admin import router as admin_router
except ImportError:
    from routes.admin import router as admin_router

try:
    from agent_backend.usage_service import (
        check_test_run_limit,
        reserve_test_run,
        complete_test_run,
        fail_test_run,
        get_idempotent_test_run,
        queue_test_run,
        cancel_test_run,
    )
    from agent_backend.plans import get_plan_config
except ImportError:
    from usage_service import (
        check_test_run_limit,
        reserve_test_run,
        complete_test_run,
        fail_test_run,
        get_idempotent_test_run,
        queue_test_run,
        cancel_test_run,
    )
    from plans import get_plan_config

try:
    from agent_backend.worker import run_worker_loop, stop_worker
except ImportError:
    from worker import run_worker_loop, stop_worker


class RunTestsRequest(BaseModel):
    base_url: Optional[str] = "http://127.0.0.1:8000"
    openapi_url: Optional[str] = None
    project_id: Optional[int] = None
    idempotency_key: Optional[str] = None


class CreateTestRunRequest(BaseModel):
    base_url: Optional[str] = None
    openapi_url: Optional[str] = None
    project_id: Optional[int] = None
    idempotency_key: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = None
    if os.getenv("ENABLE_BACKGROUND_WORKER", "true").lower() in ("true", "1", "yes"):
        worker_task = asyncio.create_task(run_worker_loop())
    yield
    stop_worker()
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI API Testing Agent",
    description="Backend for automated API testing",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(analytics_router)
app.include_router(admin_router)





FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173"
).rstrip("/")

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to assign and propagate a unique X-Request-ID across the request lifecycle.
    """
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)


app.add_middleware(CorrelationIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "AI Testing Agent Backend is running"
    }


@app.get("/health/live")
def health_live():
    """Liveness probe: verifies the backend application process is alive."""
    return {
        "status": "alive",
        "service": "ai-api-testing-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@app.get("/health/ready")
def health_ready():
    """
    Readiness probe: verifies database connectivity, worker slots availability,
    and AI provider configuration. Returns 503 if dependencies are unhealthy.
    """
    checks = {}
    # 1. Database connectivity
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:60]}"

    # 2. Worker slots check
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS total FROM worker_slots")
        slots_cnt = cursor.fetchone()["total"]
        cursor.close()
        conn.close()
        checks["worker_slots"] = slots_cnt
    except Exception as e:
        checks["worker_slots"] = f"error: {str(e)[:60]}"

    # 3. AI provider configuration
    ai_configured = bool(os.getenv("GEMINI_API_KEY"))
    checks["ai_provider"] = "configured" if ai_configured else "not_configured"

    is_ready = checks.get("database") == "connected" and isinstance(checks.get("worker_slots"), int)
    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks}
        )

    return {
        "status": "ready",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/run-tests")
def run_tests(
    config: Optional[RunTestsRequest] = None,
    current_user: dict = Depends(get_current_user),
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key")
):
    idempotency_key = (
        idempotency_key_header
        or (config.idempotency_key if config else None)
    )
    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    # Fast-path idempotency check for existing completed or running run
    if idempotency_key:
        try:
            existing_run = get_idempotent_test_run(current_user["id"], idempotency_key)
            if existing_run:
                if existing_run["status"] == "completed":
                    connection = get_db_connection()
                    cursor = connection.cursor(dictionary=True)
                    cursor.execute(
                        """
                        SELECT id, run_id, test_id, method, endpoint, category,
                               status, failure_type, expected_status, expected_body,
                               actual_status, request_body, actual_body, failure_reason
                        FROM test_results WHERE run_id = %s ORDER BY id
                        """,
                        (existing_run["id"],)
                    )
                    cached_results = cursor.fetchall()
                    cursor.close()
                    connection.close()

                    pass_rate = round(
                        (existing_run["passed_tests"] / existing_run["total_tests"]) * 100, 2
                    ) if existing_run["total_tests"] else 0

                    return {
                        "status": "success",
                        "idempotent_replay": True,
                        "data": {
                            "total": existing_run["total_tests"],
                            "passed": existing_run["passed_tests"],
                            "failed": existing_run["failed_tests"],
                            "pass_rate": pass_rate,
                            "run_id": existing_run["id"],
                            "results": cached_results
                        }
                    }
                elif existing_run["status"] == "running":
                    return {
                        "status": "in_progress",
                        "message": "A test run with this idempotency key is currently running.",
                        "idempotent_replay": True,
                        "data": {
                            "run_id": existing_run["id"],
                            "status": "running"
                        }
                    }
        except Exception:
            pass

    user_plan = current_user.get("plan", "internal_demo")
    check_test_run_limit(current_user["id"], user_plan=user_plan)

    project_id = config.project_id if config else None
    base_url = config.base_url if config and config.base_url else "http://127.0.0.1:8000"
    openapi_url = config.openapi_url if config else None

    # If project_id is provided, verify ownership and load configuration
    if project_id is not None:
        project = db_operations.get_project_by_id(project_id)
        if not project or project.get("user_id") != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        # Use project base_url/openapi_url if not explicitly customized in request
        if not config or not config.base_url or config.base_url == "http://127.0.0.1:8000":
            base_url = project["base_url"]
        if not openapi_url and project.get("openapi_url"):
            openapi_url = project["openapi_url"]

    # Plan feature entitlements
    plan_cfg = get_plan_config(user_plan)
    features = plan_cfg.get("features", [])
    enable_ai_gen = "ai_generation" in features
    enable_ai_analysis = "ai_analysis" in features

    # Atomically reserve a test run slot
    run_id = reserve_test_run(
        user_id=current_user["id"],
        project_id=project_id,
        user_plan=user_plan,
        idempotency_key=idempotency_key
    )

    run_kwargs = {
        "base_url": base_url,
        "openapi_url": openapi_url,
        "user_id": current_user["id"],
        "project_id": project_id,
    }
    if not enable_ai_gen:
        run_kwargs["enable_ai_generation"] = False
    if not enable_ai_analysis:
        run_kwargs["enable_ai_analysis"] = False
    if run_id is not None:
        run_kwargs["run_id"] = run_id
    if user_plan is not None and user_plan != "internal_demo":
        run_kwargs["user_plan"] = user_plan

    try:
        result = run_all_tests(**run_kwargs)
    except Exception as e:
        if run_id is not None:
            fail_test_run(run_id)
        raise e

    return {
        "status": "success",
        "data": result
    }


@app.post("/test-runs", status_code=status.HTTP_202_ACCEPTED)
def queue_test_run_endpoint(
    req: Optional[CreateTestRunRequest] = None,
    current_user: dict = Depends(get_current_user),
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """
    Submit a test run for asynchronous background execution.
    - Validates project ownership and configurations.
    - Validates idempotency key against request payload hash (returning 409 if reused with different payload).
    - Checks monthly quota allocations under atomic user row lock.
    - Enqueues test run in MySQL with status='queued'.
    - Returns HTTP 202 Accepted immediately.
    """
    idempotency_key = idempotency_key_header or (req.idempotency_key if req else None)
    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    project_id = req.project_id if req else None
    base_url = req.base_url if req and req.base_url else None
    openapi_url = req.openapi_url if req else None

    # If project_id is provided, verify ownership and inherit configured URLs
    if project_id is not None:
        project = db_operations.get_project_by_id(project_id)
        if not project or project.get("user_id") != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        if not base_url:
            base_url = project.get("base_url")
        if not openapi_url and project.get("openapi_url"):
            openapi_url = project.get("openapi_url")

    user_plan = current_user.get("plan", "internal_demo")

    # Queue test run atomically
    run_id = queue_test_run(
        user_id=current_user["id"],
        project_id=project_id,
        base_url=base_url,
        openapi_url=openapi_url,
        user_plan=user_plan,
        idempotency_key=idempotency_key
    )

    run = db_operations.get_user_test_run_by_id(run_id, current_user["id"])
    run_status = run.get("status", "queued") if run else "queued"

    return {
        "status": "accepted" if run_status in ("queued", "running") else "success",
        "message": f"Test run {run_status} successfully",
        "data": {
            "run_id": run_id,
            "status": run_status,
            "idempotent_replay": bool(idempotency_key and run_status in ("completed", "running"))
        }
    }


@app.get("/test-runs/{run_id}")
def get_test_run_status_endpoint(
    run_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Retrieve live status and progress metrics of a test run.
    Guarantees strict multi-tenant isolation.
    """
    run = db_operations.get_user_test_run_by_id(run_id, current_user["id"])
    if not run:
        candidate = db_operations.get_test_run_by_id(run_id)
        if candidate and candidate.get("user_id") == current_user["id"]:
            run = candidate
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test run not found"
        )
    return {
        "status": "success",
        "data": run
    }


@app.post("/test-runs/{run_id}/cancel")
def cancel_test_run_endpoint(
    run_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Cancel an in-flight or queued test run.
    Transitions status to 'cancelled', releases quota reservation and worker slot.
    """
    run = db_operations.get_user_test_run_by_id(run_id, current_user["id"])
    if not run:
        candidate = db_operations.get_test_run_by_id(run_id)
        if candidate and candidate.get("user_id") == current_user["id"]:
            run = candidate
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test run not found"
        )

    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel test run with status '{run['status']}'"
        )

    success = cancel_test_run(run_id, user_id=current_user["id"])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to cancel test run"
        )

    return {
        "status": "success",
        "message": "Test run cancelled successfully",
        "data": {
            "run_id": run_id,
            "status": "cancelled"
        }
    }


@app.get("/test-runs")
def get_test_runs_endpoint(
    project_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    if project_id is not None:
        runs = db_operations.get_test_runs(
            user_id=current_user["id"],
            project_id=project_id
        )
    else:
        runs = db_operations.get_test_runs(
            user_id=current_user["id"]
        )

    return {
        "status": "success",
        "data": runs
    }




@app.get("/test-runs/{run_id}/results")
def get_test_results(
    run_id: int,
    current_user: dict = Depends(get_current_user)
):
    run = db_operations.get_user_test_run_by_id(run_id, current_user["id"])
    if not run:
        candidate = db_operations.get_test_run_by_id(run_id)
        if candidate and candidate.get("user_id") == current_user["id"]:
            run = candidate
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test run not found"
        )

    if run.get("status") in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Test run is currently '{run['status']}'. Results are not available yet."
        )

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
def get_bug_reports(
    run_id: int,
    current_user: dict = Depends(get_current_user)
):
    run = db_operations.get_user_test_run_by_id(run_id, current_user["id"])
    if not run:
        candidate = db_operations.get_test_run_by_id(run_id)
        if candidate and candidate.get("user_id") == current_user["id"]:
            run = candidate
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test run not found"
        )

    if run.get("status") in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Test run is currently '{run['status']}'. Bug reports are not available yet."
        )

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

