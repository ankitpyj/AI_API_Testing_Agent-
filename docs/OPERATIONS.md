# AI API Testing Agent — Operations Guide (`docs/OPERATIONS.md`)

## 1. System Architecture Overview

The AI API Testing Agent is a production-grade multi-tenant SaaS platform composed of:
- **Frontend**: React 19 SPA built with Vite, deployed on Render Static Sites.
- **Backend**: FastAPI (Python 3.11/3.13) running under Uvicorn, serving REST APIs and managing background execution.
- **Database**: Cloud MySQL hosted on Aiven with SSL enforcement (`ca.pem`).
- **AI Engine**: Google Gemini API via an OpenAI-compatible client interface with exponential backoff retries.
- **Job Engine**: Native MySQL FIFO queue with pessimistic locking (`SELECT ... FOR UPDATE SKIP LOCKED`), worker slots concurrency control, cooperative cancellation, and heartbeat leases.

```
+-----------------------------------------------------------------------------------+
|                                  USER BROWSER                                     |
|                      React 19 Dashboard (Render Static Site)                      |
+-----------------------------------------------------------------------------------+
                                        |  HTTPS (JWT Auth, X-Request-ID)
                                        v
+-----------------------------------------------------------------------------------+
|                              FASTAPI API BACKEND                                  |
|   POST /test-runs (202 Accepted)   |   GET /test-runs/{id}   |   /health/live     |
|   POST /test-runs/{id}/cancel      |   /health/ready         |   /admin/metrics   |
+-----------------------------------------------------------------------------------+
                               |                     ^
             Enqueues Job      |                     | Heartbeat & Results
             (status='queued') v                     | (status='completed'/'failed')
+-----------------------------------------------------------------------------------+
|                        MYSQL DATABASE (AIVEN CLOUD)                               |
|   - test_runs (FIFO Queue)         - users & projects                             |
|   - worker_slots (Concurrency)     - test_results & bug_reports                   |
+-----------------------------------------------------------------------------------+
                               ^                     |
             Claims Job Slot   |                     | Executes Run & AI Diagnostics
             (SKIP LOCKED)     |                     v
+-----------------------------------------------------------------------------------+
|                           BACKGROUND WORKER ENGINE                                |
|   - Embedded Lifespan Loop (Option A) OR Dedicated Worker Service (Option B)       |
|   - Cooperative cancellation tokens, 5-minute lease heartbeats, zombie fencing    |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
                            TARGET API UNDER TEST (HTTP/S)
```

---

## 2. Worker Lifecycle & Concurrency Model

### 2.1 FIFO Job Processing Flow
1. **Submission**: User sends `POST /test-runs`. The endpoint validates project ownership, checks plan quotas, records an idempotency key, inserts a record into `test_runs` with `status = 'queued'`, and immediately returns HTTP `202 Accepted` with `{ "run_id": 101, "status": "queued" }`.
2. **Claiming**: The worker loop calls `claim_next_queued_job(worker_id, max_concurrent_running)`. In a single database transaction:
   - It acquires an unassigned or expired slot from `worker_slots` (`slot_id <= max_concurrent_running`) using `SELECT ... FOR UPDATE SKIP LOCKED`.
   - If no slot is free, the transaction rolls back cleanly without lock contention.
   - It claims the oldest eligible job (`status = 'queued'`) in FIFO order using `FOR UPDATE SKIP LOCKED`.
   - Transitions job status to `running`, records `started_at`, `worker_id`, `heartbeat_at`, and sets a 5-minute lease expiry.
3. **Execution**: The worker decrypts project credentials into memory, starts a background heartbeat thread (`JobHeartbeatManager`, refreshing every 30 seconds), runs OpenAPI parsing, test generation, test execution, and AI failure diagnostics.
4. **Completion & Fencing**:
   - `save_all_test_results_and_bugs()` atomically inserts all results and bugs in a single transaction while verifying that `worker_id` matches the current lease holder.
   - `complete_test_run()` transitions status to `completed` and records test counts.
   - `release_worker_slot()` frees the worker slot in `worker_slots`.

### 2.2 Cooperative Cancellation
- When a user issues `POST /test-runs/{id}/cancel`, `cancel_test_run()` immediately sets `status = 'cancelled'`.
- The worker checks `is_run_cancelled(run_id)` before each execution stage and between test batches.
- If cancelled, the worker raises `TestRunCancelledError`, aborts remaining requests, skips completion persistence, and releases its worker slot cleanly.

---

## 3. Scaling & Deployment Topologies

### Option A: Unified Web + Worker (Default on Render Starter)
- **Configuration**: `ENABLE_BACKGROUND_WORKER=true`, single Render Web service.
- **Characteristics**: Cost-effective, zero extra hosting cost, worker loop runs inside FastAPI's lifespan.
- **Constraints**: Uvicorn worker count must remain `workers = 1` to prevent multiple competing lifespan loops. Global concurrency is governed by `worker_slots` (default: 3 slots).

### Option B: Decoupled Web + Worker (Production Recommended)
- **Configuration**:
  - Web service: `ENABLE_BACKGROUND_WORKER=false`, can scale horizontally to multiple instances.
  - Dedicated worker service: Render background worker running `python -m agent_backend.worker`.
- **Advantages**: Heavy test execution and AI model requests never starve incoming web HTTP requests.

---

## 4. Key & Secret Rotation Procedures

### 4.1 JWT Secret Key Rotation
1. Generate a new 64-character hex key:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update `JWT_SECRET_KEY` in the Render environment variables.
3. Trigger a redeploy. Existing user sessions will expire cleanly and prompt a re-login.

### 4.2 Project Secret Encryption Key Rotation
1. Projects store encrypted API secrets using AES-256-GCM.
2. When rotating `PROJECT_SECRET_ENCRYPTION_KEY`:
   - Run the migration utility script to re-encrypt existing `auth_secret_encrypted` rows with the new key.
   - Update `PROJECT_SECRET_ENCRYPTION_KEY` in Render environment settings.

---

## 5. Routine Database Maintenance

- **Stale Reservation Reconciliation**: Handled automatically every polling loop cycle by `reconcile_stale_reservations()`. Any running job whose heartbeat has expired (> 5 minutes) is marked failed and its slot released.
- **Worker Slot Reset**: If an unexpected machine hard power-off leaves dirty slots:
  ```sql
  UPDATE worker_slots SET run_id = NULL, worker_id = NULL, leased_until = NULL WHERE leased_until < UTC_TIMESTAMP();
  ```
