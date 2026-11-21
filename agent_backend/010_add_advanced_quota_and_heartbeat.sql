-- Migration 010: Advanced Quota Reservation, Heartbeat, and Idempotency Fields
-- Adds estimated_tests, heartbeat_at, reservation_expires_at, and idempotency_key to test_runs.

ALTER TABLE test_runs
    ADD COLUMN estimated_tests INT NOT NULL DEFAULT 0,
    ADD COLUMN heartbeat_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN reservation_expires_at TIMESTAMP NULL DEFAULT NULL,
    ADD COLUMN idempotency_key VARCHAR(128) NULL DEFAULT NULL;

-- Create index for user-scoped idempotency lookup
CREATE INDEX idx_test_runs_user_idempotency ON test_runs (user_id, idempotency_key);

-- Create index for heartbeat and stale reservation reconciliation
CREATE INDEX idx_test_runs_heartbeat ON test_runs (status, heartbeat_at);
