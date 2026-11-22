"""
Background Test Execution Worker Engine.

Provides asynchronous, MySQL-backed FIFO test suite execution:
- Atomically claims queued jobs using worker_slots and SELECT ... FOR UPDATE SKIP LOCKED.
- Enforces max worker concurrency without external queuing systems (Redis/Celery).
- Runs test execution in background worker threads without blocking FastAPI's event loop.
- Supports periodic heartbeat updates and cooperative job cancellation.
- Sanitizes failure error messages and guarantees slot cleanup on finish/failure/cancellation.
"""

import os
import sys
import socket
import asyncio
from uuid import uuid4
from typing import Optional, Dict, Any

try:
    from database import get_db_connection
    from db_operations import (
        get_user_by_id,
        get_project_by_id,
        claim_next_queued_job,
        release_worker_slot,
    )
    from usage_service import (
        reconcile_stale_reservations,
        fail_test_run,
        complete_test_run,
        cancel_test_run,
    )
    from plans import get_plan_config
    from engine.test_generator.test_executor import run_all_tests, TestRunCancelledError
    from engine.authentication.response_sanitizer import sanitize_error_message
except ImportError:
    from agent_backend.database import get_db_connection
    from agent_backend.db_operations import (
        get_user_by_id,
        get_project_by_id,
        claim_next_queued_job,
        release_worker_slot,
    )
    from agent_backend.usage_service import (
        reconcile_stale_reservations,
        fail_test_run,
        complete_test_run,
        cancel_test_run,
    )
    from agent_backend.plans import get_plan_config
    from agent_backend.engine.test_generator.test_executor import run_all_tests, TestRunCancelledError
    from agent_backend.engine.authentication.response_sanitizer import sanitize_error_message


def generate_worker_id(hostname: Optional[str] = None, pid: Optional[int] = None) -> str:
    """
    Generate a bounded, collision-resistant worker identifier <= 64 chars.
    Preserves full 32-character UUID4 hex entropy while bounding the hostname slug to 12 chars.
    Format: w-{hostname_slug}-{pid}-{uuid4_hex}
    Max length: 2 + 12 + 1 + 7 + 1 + 32 = 55 chars (strictly <= 64 chars).
    """
    raw_host = hostname if hostname is not None else socket.gethostname()
    host_slug = raw_host.split(".")[0][:12]
    proc_pid = pid if pid is not None else os.getpid()
    wid = f"w-{host_slug}-{proc_pid}-{uuid4().hex}"
    assert len(wid) <= 64, f"Worker ID exceeds 64 characters: {len(wid)}"
    return wid


WORKER_ID = generate_worker_id()
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", "3"))
POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))

_worker_running = True


def execute_job(job: Dict[str, Any]) -> None:
    """
    Execute a claimed test run synchronously inside a dedicated worker thread.
    - Decrypts project credentials in memory for the duration of the run only.
    - Resolves target URL and plan entitlements.
    - Invokes run_all_tests with run_id and cooperative cancellation support.
    - On unexpected exception: sanitizes error trace and marks run as failed.
    - Guaranteed cleanup: releases worker slot in worker_slots.
    """
    run_id = job["id"]
    user_id = job["user_id"]
    project_id = job.get("project_id")
    base_url = job.get("base_url")
    openapi_url = job.get("openapi_url")

    print(f"[Worker {WORKER_ID}] Starting execution of run {run_id} (project={project_id}, user={user_id})")

    try:
        # 1. Resolve user plan & entitlements
        user = get_user_by_id(user_id)
        user_plan = user.get("plan", "internal_demo") if user else "internal_demo"
        plan_cfg = get_plan_config(user_plan)
        features = plan_cfg.get("features", [])
        enable_ai_gen = "ai_generation" in features
        enable_ai_analysis = "ai_analysis" in features

        # 2. Resolve project configuration and decrypted credentials if applicable
        target_base_url = base_url
        target_openapi_url = openapi_url
        if project_id:
            project = get_project_by_id(project_id, include_secret=True)
            if project:
                if not target_base_url or target_base_url == "http://127.0.0.1:8000":
                    target_base_url = project.get("base_url", "http://127.0.0.1:8000")
                if not target_openapi_url and project.get("openapi_url"):
                    target_openapi_url = project.get("openapi_url")

        run_kwargs = {
            "base_url": target_base_url or "http://127.0.0.1:8000",
            "openapi_url": target_openapi_url,
            "user_id": user_id,
            "project_id": project_id,
            "run_id": run_id,
            "user_plan": user_plan,
            "enable_ai_generation": enable_ai_gen,
            "enable_ai_analysis": enable_ai_analysis,
            "worker_id": WORKER_ID,
        }

        # 3. Execute test suite
        run_all_tests(**run_kwargs)
        print(f"[Worker {WORKER_ID}] Finished execution of run {run_id} successfully.")

    except TestRunCancelledError:
        print(f"[Worker {WORKER_ID}] Run {run_id} was cancelled by user; halted execution.")
    except Exception as exc:
        print(f"[Worker {WORKER_ID}] Exception during run {run_id}: {exc}")
        clean_msg = sanitize_error_message(exc, max_length=1000)
        try:
            fail_test_run(run_id, error_message=clean_msg, worker_id=WORKER_ID)
        except Exception as fail_err:
            print(f"[Worker {WORKER_ID}] Failed to mark run {run_id} as failed: {fail_err}")
    finally:
        # 4. Guarantee slot release (scoped strictly to WORKER_ID)
        try:
            release_worker_slot(run_id, worker_id=WORKER_ID)
        except Exception:
            pass


async def run_worker_loop():
    """
    Main asynchronous worker polling loop.
    Periodically checks for queued test runs and executes them using worker threads.
    """
    global _worker_running
    print(f"[Background Worker] Worker loop started ({WORKER_ID}, concurrency={MAX_CONCURRENT_WORKERS})")
    
    while _worker_running:
        try:
            # 1. Periodic stale reservation recovery
            try:
                reconcile_stale_reservations(timeout_minutes=5)
            except Exception:
                pass

            # 2. Attempt to claim next queued job atomically
            job = claim_next_queued_job(WORKER_ID, max_concurrent_running=MAX_CONCURRENT_WORKERS)
            if job is not None:
                print(f"[Background Worker] Claimed job {job['id']} on slot {job.get('slot_id')}")
                # Execute asynchronously via worker thread
                asyncio.create_task(asyncio.to_thread(execute_job, job))
                # Yield control briefly to event loop before checking for more jobs
                await asyncio.sleep(0.05)
                continue
        except Exception as loop_err:
            print(f"[Background Worker] Error in worker polling loop: {loop_err}")

        await asyncio.sleep(POLL_INTERVAL)


def stop_worker():
    """Signal worker polling loop to stop gracefully."""
    global _worker_running
    _worker_running = False
    print(f"[Background Worker] Worker loop stopped ({WORKER_ID})")


if __name__ == "__main__":
    print(f"Starting standalone AI API Testing Agent Worker ({WORKER_ID})...")
    try:
        asyncio.run(run_worker_loop())
    except (KeyboardInterrupt, SystemExit):
        stop_worker()
        print(f"Worker {WORKER_ID} terminated.")
