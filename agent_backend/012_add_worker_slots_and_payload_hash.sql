-- Migration 012: Dedicated Worker Slot Reservation Table & Idempotency Payload Hash
-- Solves worker concurrency race condition with atomic slot reservation (SELECT FOR UPDATE SKIP LOCKED).
-- Adds payload_hash column to test_runs for request payload validation on idempotency replay.

-- 1. Add payload_hash to test_runs table
ALTER TABLE test_runs
    ADD COLUMN payload_hash VARCHAR(64) NULL AFTER idempotency_key;

-- 2. Create worker_slots table for atomic distributed concurrency control
CREATE TABLE IF NOT EXISTS worker_slots (
    slot_id INT NOT NULL PRIMARY KEY,
    run_id INT NULL UNIQUE,
    worker_id VARCHAR(64) NULL,
    leased_until TIMESTAMP NULL,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_worker_slots_lease (leased_until),
    FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 3. Pre-seed worker slots 1 through 20 for dynamic concurrency allocation
INSERT IGNORE INTO worker_slots (slot_id) VALUES
    (1), (2), (3), (4), (5), (6), (7), (8), (9), (10),
    (11), (12), (13), (14), (15), (16), (17), (18), (19), (20);
