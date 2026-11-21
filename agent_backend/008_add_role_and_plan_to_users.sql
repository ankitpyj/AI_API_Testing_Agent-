-- Migration 008: Add role and plan columns to users table
-- Defaults: role='user', plan='internal_demo'

ALTER TABLE users 
ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user' AFTER password_hash,
ADD COLUMN plan VARCHAR(50) NOT NULL DEFAULT 'internal_demo' AFTER role;
