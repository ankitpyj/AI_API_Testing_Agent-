-- Migration 005: Add project_id column to test_runs
ALTER TABLE test_runs
ADD COLUMN project_id INT NULL DEFAULT NULL AFTER user_id,
ADD INDEX idx_test_runs_project_id (project_id),
ADD CONSTRAINT fk_test_runs_project_id
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE SET NULL;
