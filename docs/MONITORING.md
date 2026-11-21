# Production Monitoring & Alerting Guide (`docs/MONITORING.md`)

## 1. Monitoring Architecture

The AI API Testing Agent exposes observability signals across three layers:
1. **Health Check Probes** (Liveness and Readiness endpoints for container orchestrators & uptime monitors).
2. **Operational Telemetry APIs** (Admin worker metrics, slot utilization, queue depth).
3. **Structured JSON Application Logs** (Request correlation IDs, worker events, error traces).

---

## 2. Health Check Endpoints

### 2.1 Liveness Probe (`GET /health/live`)
- **Purpose**: Verifies that the FastAPI process is active and accepting requests.
- **Port**: 5000 / $PORT
- **Response**: HTTP 200 OK
  ```json
  {
    "status": "alive",
    "service": "ai-api-testing-backend",
    "timestamp": "2026-11-20T11:20:00.000000+00:00",
    "version": "1.0.0"
  }
  ```

### 2.2 Readiness Probe (`GET /health/ready`)
- **Purpose**: Deep verification of external dependencies before routing traffic.
- **Checks**:
  - `database`: Executes `SELECT 1` on Aiven MySQL.
  - `worker_slots`: Verifies worker slot table availability.
  - `ai_provider`: Verifies `GEMINI_API_KEY` configuration.
- **Response**:
  - Healthy: HTTP 200 OK
    ```json
    {
      "status": "ready",
      "checks": {
        "database": "connected",
        "worker_slots": 5,
        "ai_provider": "configured"
      },
      "timestamp": "2026-11-20T11:20:00.000000+00:00"
    }
    ```
  - Unhealthy: HTTP 503 Service Unavailable

---

## 3. Operational Worker Metrics (`GET /admin/worker-metrics`)

Accessible by platform administrators with Bearer JWT token:
```json
{
  "status": "healthy",
  "slots": {
    "total": 5,
    "active": 2,
    "available": 3,
    "utilization_percent": 40.0
  },
  "queue": {
    "depth": 1,
    "running": 2
  },
  "recent_24h": {
    "completed": 124,
    "failed": 3,
    "cancelled": 5,
    "avg_duration_seconds": 18.4
  },
  "timestamp": "2026-11-20T11:20:00.000000+00:00"
}
```

---

## 4. Structured JSON Logging & Request Correlation

Every log record emitted by the backend or worker is formatted as single-line JSON with standardized attributes:

```json
{
  "timestamp": "2026-11-20T11:20:01.123456+00:00",
  "level": "INFO",
  "logger": "agent_backend",
  "message": "Claimed job 101 on slot 2",
  "module": "worker",
  "func": "run_worker_loop",
  "line": 151,
  "request_id": "8f8b50f9-2b0e-4ab8-922e-13a89047b2c9",
  "worker_id": "worker-render-web-1-a1b2c3"
}
```

### Correlation ID Flow (`X-Request-ID`):
1. Incoming HTTP requests are intercepted by `CorrelationIdMiddleware`.
2. If `X-Request-ID` header is present, it is preserved; otherwise a new UUIDv4 is generated.
3. The ID is stored in Python's `contextvars.ContextVar` (`request_id_ctx`).
4. All logs emitted during the request automatically include `"request_id"`.
5. The response includes `X-Request-ID` in its HTTP response headers.

---

## 5. Recommended Alert Thresholds

| Metric | Warning Threshold | Critical Threshold | Recommended Action |
| :--- | :--- | :--- | :--- |
| **Queue Depth** | > 10 queued jobs | > 25 queued jobs | Scale up `MAX_CONCURRENT_WORKERS` or migrate to Option B dedicated workers |
| **Slot Utilization** | > 80% for > 5 min | 100% for > 10 min | Add more worker slots in `worker_slots` table |
| **Readiness Failures** | 1 failure | 3 consecutive failures | Check Aiven MySQL connectivity and SSL certificate validity |
| **24h Job Failure Rate** | > 10% of runs | > 25% of runs | Inspect Gemini API quota / rate limits and target API stability |
| **Zombie Leases** | > 2 per hour | > 5 per hour | Investigate potential worker container out-of-memory (OOM) kills on Render |
