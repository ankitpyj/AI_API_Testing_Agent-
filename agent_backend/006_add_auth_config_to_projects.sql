-- Migration 006: Add Authentication Configuration to Projects
-- Supports public (none), Bearer token, and custom API Key headers.
-- Secrets are encrypted using AES-256-GCM before storage.

ALTER TABLE projects
    ADD COLUMN auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
    ADD COLUMN auth_header_name VARCHAR(100) NULL DEFAULT NULL,
    ADD COLUMN auth_secret_encrypted TEXT NULL DEFAULT NULL;
