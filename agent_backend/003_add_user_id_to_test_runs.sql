-- Migration: Add user_id column and foreign key to test_runs
ALTER TABLE test_runs
ADD COLUMN user_id INT NULL DEFAULT NULL AFTER id,
ADD INDEX idx_test_runs_user_id (user_id),
ADD CONSTRAINT fk_test_runs_user_id
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE SET NULL;
