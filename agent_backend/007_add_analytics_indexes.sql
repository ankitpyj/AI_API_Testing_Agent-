-- Migration 007: Add analytics index to test_runs
-- Speeds up analytics queries filtering by user_id and started_at date range

ALTER TABLE test_runs ADD INDEX idx_test_runs_user_started (user_id, started_at);
