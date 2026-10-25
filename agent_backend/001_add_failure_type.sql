-- Migration: add failure_type column to test_results
-- Run once against the Aiven MySQL database before deploying updated backend.
-- Safe to re-run: MySQL will raise an error if the column already exists,
-- which you can safely ignore.

ALTER TABLE test_results
    ADD COLUMN failure_type VARCHAR(50) NULL
    AFTER status;

-- Verify
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'test_results'
  AND COLUMN_NAME = 'failure_type';
