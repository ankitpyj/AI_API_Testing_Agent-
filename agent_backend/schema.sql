CREATE TABLE IF NOT EXISTS test_runs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    started_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    total_tests INT DEFAULT 0,
    passed_tests INT DEFAULT 0,
    failed_tests INT DEFAULT 0
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
