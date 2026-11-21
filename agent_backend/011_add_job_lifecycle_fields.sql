-- Migration 011: Background Job Lifecycle, Timing, Worker Assignment, and Target Configuration
-- Adds created_at, completed_at, base_url, openapi_url, error_message, worker_id to test_runs.
-- Adds index idx_test_runs_queue_claim for atomic FIFO worker claiming.

-- 1. Add created_at, completed_at, base_url, openapi_url, error_message, worker_id to test_runs
ALTER TABLE test_runs
    ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP AFTER project_id,
    ADD COLUMN completed_at TIMESTAMP NULL DEFAULT NULL AFTER started_at,
    ADD COLUMN base_url VARCHAR(255) NULL AFTER completed_at,
    ADD COLUMN openapi_url VARCHAR(255) NULL AFTER base_url,
    ADD COLUMN error_message TEXT NULL AFTER failed_tests,
    ADD COLUMN worker_id VARCHAR(64) NULL AFTER reservation_expires_at;

-- 2. Backfill created_at from started_at for existing rows
UPDATE test_runs
SET created_at = started_at
WHERE created_at IS NULL AND started_at IS NOT NULL;

-- 3. Backfill completed_at for historical completed test runs where completed_at is null
UPDATE test_runs
SET completed_at = heartbeat_at
WHERE status = 'completed' AND completed_at IS NULL AND heartbeat_at IS NOT NULL;

-- 4. Allow started_at to be NULL for newly enqueued jobs before execution begins
ALTER TABLE test_runs MODIFY COLUMN started_at TIMESTAMP NULL DEFAULT NULL;

-- 5. Create index for atomic FIFO worker queue claiming
CREATE INDEX idx_test_runs_queue_claim ON test_runs (status, created_at, id);
