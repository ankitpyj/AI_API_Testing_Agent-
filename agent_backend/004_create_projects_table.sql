-- Migration 004: Create projects table
CREATE TABLE IF NOT EXISTS projects (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    base_url VARCHAR(255) NOT NULL,
    openapi_url VARCHAR(255) NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_projects_user_id (user_id),
    CONSTRAINT fk_projects_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
);
