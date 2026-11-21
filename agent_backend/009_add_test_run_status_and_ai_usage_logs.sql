-- Migration 009: Add lifecycle status to test_runs and create ai_usage_logs table
-- Prepares atomic quota reservation and accurate AI call telemetry

-- 1. Add status column to test_runs table
ALTER TABLE test_runs
ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'completed' AFTER failed_tests;

CREATE INDEX idx_test_runs_status ON test_runs(status);

-- 2. Create ai_usage_logs table for exact LLM API call accounting
CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    run_id INT NULL DEFAULT NULL,
    call_type VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'gemini',
    model VARCHAR(100) NOT NULL,
    input_tokens INT NULL DEFAULT NULL,
    output_tokens INT NULL DEFAULT NULL,
    total_tokens INT NULL DEFAULT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ai_logs_user_id (user_id),
    INDEX idx_ai_logs_run_id (run_id),
    INDEX idx_ai_logs_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE SET NULL
);
