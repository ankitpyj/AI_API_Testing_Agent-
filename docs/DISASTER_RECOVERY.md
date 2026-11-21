# Disaster Recovery & Fault Tolerance Guide (`docs/DISASTER_RECOVERY.md`)

## 1. Incident Scenarios & Recovery Strategies

This document defines standard recovery procedures for infrastructure failures, process terminations, database disruptions, and token leaks.

---

## 2. Worker Process Crash Mid-Execution

### Scenario
A background worker process executing a test suite is abruptly killed (e.g., Render restart, OOM, host maintenance).

### Automatic Recovery Protocol
1. **Heartbeat Expiration**: When the worker crashes, its background heartbeat thread ceases updating `heartbeat_at` in `test_runs` and `leased_until` in `worker_slots`.
2. **Reconciliation Loop**: The next active worker cycle invokes `reconcile_stale_reservations()`.
3. **Failsafe Transition**: Any job whose lease has expired (> 5 minutes) is transitioned to `status = 'failed'` with the error message:
   `"Execution abandoned: worker heartbeat timed out"`.
4. **Slot Recycling**: The abandoned slot in `worker_slots` is unlocked and made available to subsequent queued jobs.
5. **Zombie Fencing**: If the crashed worker resumes execution out-of-order, its attempts to persist results (`save_all_test_results_and_bugs`) or complete the run (`complete_test_run`) are rejected with `RuntimeError("worker ownership mismatch")` because the lease ownership was transferred.

---

## 3. Database Outage & Point-In-Time Recovery (Aiven MySQL)

### Backup Verification
Aiven Cloud MySQL performs continuous write-ahead logging (binlog) and automated daily snapshots with Point-In-Time Recovery (PITR) up to 7 days.

### Failover Procedure
1. If the primary database node experiences hardware failure, Aiven automatically triggers failover to a standby replica with automatic DNS updates.
2. In the event of catastrophic data corruption:
   - Navigate to the Aiven Console -> Services -> `ai-api-testing-db` -> **Backups**.
   - Select **Fork Service / Point-in-time Recovery** to restore to a timestamp prior to the incident.
   - Update `DB_HOST` in Render environment variables.
   - Run verification probe: `GET /health/ready`.

---

## 4. Emergency Database State Reset Commands

If manual administrative intervention is required to unlock corrupted worker slots or stuck runs:

```sql
-- 1. Free all expired worker slots
UPDATE worker_slots
SET run_id = NULL, worker_id = NULL, leased_until = NULL
WHERE leased_until IS NOT NULL AND leased_until < UTC_TIMESTAMP();

-- 2. Mark stuck running jobs older than 30 minutes as failed
UPDATE test_runs
SET status = 'failed',
    error_message = 'Manual recovery: execution halted due to system maintenance',
    completed_at = NOW()
WHERE status = 'running'
  AND started_at < DATE_SUB(NOW(), INTERVAL 30 MINUTE);

-- 3. Verify slot availability
SELECT slot_id, run_id, worker_id, leased_until FROM worker_slots;
```

---

## 5. Security Incident & Secret Leak Protocol

If `JWT_SECRET_KEY` or `PROJECT_SECRET_ENCRYPTION_KEY` is suspected to be compromised:
1. Immediately generate new keys:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update the variables in Render Service Dashboard.
3. Invalidate all active JWT tokens by deploying the updated secret.
4. Notify affected users to rotate target API credentials saved under their projects.
