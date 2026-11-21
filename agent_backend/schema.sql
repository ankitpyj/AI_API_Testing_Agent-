CREATE TABLE IF NOT EXISTS test_runs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL DEFAULT NULL,
    project_id INT NULL DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL DEFAULT NULL,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    base_url VARCHAR(255) NULL DEFAULT NULL,
    openapi_url VARCHAR(255) NULL DEFAULT NULL,
    total_tests INT DEFAULT 0,
    passed_tests INT DEFAULT 0,
    failed_tests INT DEFAULT 0,
    error_message TEXT NULL DEFAULT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    estimated_tests INT NOT NULL DEFAULT 0,
    heartbeat_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    reservation_expires_at TIMESTAMP NULL DEFAULT NULL,
    idempotency_key VARCHAR(128) NULL DEFAULT NULL,
    worker_id VARCHAR(64) NULL DEFAULT NULL,
    INDEX (user_id),
    INDEX (project_id),
    INDEX (status),
    INDEX idx_test_runs_user_idempotency (user_id, idempotency_key),
    INDEX idx_test_runs_heartbeat (status, heartbeat_at),
    INDEX idx_test_runs_queue_claim (status, created_at, id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);



CREATE TABLE IF NOT EXISTS test_results (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    test_id VARCHAR(50),
    method VARCHAR(10),
    endpoint VARCHAR(255),
    category VARCHAR(50),
    status VARCHAR(10),
    expected_status INT,
    expected_body JSON,
    actual_status INT,
    request_body JSON,
    actual_body JSON,
    failure_reason TEXT,
    INDEX (run_id)
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    test_id VARCHAR(50),
    bug_id VARCHAR(50),
    endpoint VARCHAR(255),
    severity VARCHAR(20),
    summary TEXT,
    possible_cause TEXT,
    recommendation TEXT,
    status VARCHAR(20) DEFAULT 'Open',
    INDEX (run_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    plan VARCHAR(50) NOT NULL DEFAULT 'internal_demo',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    base_url VARCHAR(255) NOT NULL,
    openapi_url VARCHAR(255) NULL,
    auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
    auth_header_name VARCHAR(100) NULL DEFAULT NULL,
    auth_secret_encrypted TEXT NULL DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX (user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

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
    INDEX (user_id),
    INDEX (run_id),
    INDEX (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE SET NULL
);


