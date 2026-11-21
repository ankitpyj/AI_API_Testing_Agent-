# Production Deployment Readiness Checklist (`docs/DEPLOYMENT_CHECKLIST.md`)

## 1. Pre-Deployment Verification

Before triggering a production release to Render:

- [x] **No Secrets in Source Control**: Verified that `.env`, certificates (`ca.pem`), and private keys are in `.gitignore`.
- [x] **Database Schema Migrations**: All 11 migrations applied up through `011_create_worker_slots_and_queue.sql`.
- [x] **SSL Database Connection**: `DB_SSL_CA` points to valid CA cert and `ssl_verify_cert=True` is enabled.
- [x] **AES-256-GCM Encryption Key**: `PROJECT_SECRET_ENCRYPTION_KEY` configured with 64 hex characters (32 bytes).
- [x] **JWT Secret Key**: `JWT_SECRET_KEY` configured with random 64-character hex key.
- [x] **Gemini API Key**: `GEMINI_API_KEY` configured and tested with OpenAI-compatible endpoint.
- [x] **CORS Whitelist**: `FRONTEND_URL` strictly matched to production frontend origin.
- [x] **Single Lifespan Worker**: If using Option A on Render, Uvicorn start command must use `--workers 1`.
- [x] **Automated Tests Passing**:
  - Backend unit and regression test suite: 100% passing.
  - End-to-end background worker test suite (`tests/test_e2e_complete_workflow.py`): 100% passing.
  - Monitoring and health check suite (`tests/test_monitoring.py`): 100% passing.
  - Frontend integration test suite (`dashboard/src/**/*.test.mjs`): 100% passing (27/27).
  - Frontend production build (`npm run build`): Clean build, zero warnings.

---

## 2. Render Deployment Configuration

### 2.1 Backend Web Service (`ai-api-testing-agent`)
- **Runtime**: Python 3.11.9
- **Build Command**: `pip install --upgrade pip && pip install -r agent_backend/requirements.txt`
- **Start Command**: `uvicorn agent_backend.app:app --host 0.0.0.0 --port $PORT --workers 1`
- **Health Check Path**: `/health/ready`
- **Environment Variables**:
  - `ENABLE_BACKGROUND_WORKER`: `true`
  - `MAX_CONCURRENT_WORKERS`: `3`
  - `WORKER_POLL_INTERVAL`: `1.0`
  - `DB_HOST`: Aiven MySQL host
  - `DB_PORT`: 23618 / 3306
  - `DB_USER`: `avnadmin`
  - `DB_PASSWORD`: Managed secret
  - `DB_NAME`: `defaultdb`
  - `DB_SSL_CA`: `agent_backend/ca.pem`
  - `JWT_SECRET_KEY`: Managed secret
  - `PROJECT_SECRET_ENCRYPTION_KEY`: Managed secret
  - `GEMINI_API_KEY`: Managed secret
  - `FRONTEND_URL`: `https://ai-api-testing-dashboard.onrender.com`

### 2.2 Frontend Static Site (`ai-api-testing-dashboard`)
- **Runtime**: Static
- **Root Directory**: `dashboard`
- **Build Command**: `npm install && npm run build`
- **Publish Directory**: `./dist`
- **Rewrite Rule**: `/*` -> `/index.html` (SPA routing)
- **Environment Variables**:
  - `VITE_API_URL`: `https://ai-api-testing-agent.onrender.com`

---

## 3. Post-Deployment Smoke Test Protocol

Immediately after deployment:

1. **Verify Liveness**:
   ```bash
   curl -I https://ai-api-testing-agent.onrender.com/health/live
   # Expect: HTTP 200 OK with X-Request-ID header
   ```
2. **Verify Readiness**:
   ```bash
   curl https://ai-api-testing-agent.onrender.com/health/ready
   # Expect: HTTP 200 OK with {"status": "ready", "checks": {"database": "connected", "worker_slots": 5, ...}}
   ```
3. **Verify Frontend Loading**:
   Open `https://ai-api-testing-dashboard.onrender.com` in browser, verify dark/light mode, login screen.
4. **End-to-End Test Run**:
   - Log into dashboard.
   - Select a project.
   - Click "Run Tests".
   - Confirm immediate `202 Accepted` response.
   - Verify indeterminate sweep progress bar during execution.
   - Verify polling transitions to Completed.
   - Inspect test results and bug reports.
   - Check History page to verify completed test run with project name.
