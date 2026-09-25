CREATE TABLE IF NOT EXISTS sync_jobs (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    stored_file_path VARCHAR(512) NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NULL,
    total_records INT UNSIGNED NOT NULL DEFAULT 0,
    success_records INT UNSIGNED NOT NULL DEFAULT 0,
    failed_records INT UNSIGNED NOT NULL DEFAULT 0,
    retry_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
    last_error_code VARCHAR(64) NULL,
    last_error_message VARCHAR(512) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    started_at DATETIME(3) NULL,
    finished_at DATETIME(3) NULL,
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_sync_jobs_idempotency_key (idempotency_key),
    KEY idx_sync_jobs_status_created (status, created_at),
    KEY idx_sync_jobs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sync_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    external_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    record_date DATE NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_sync_records_job_external (job_id, external_id),
    KEY idx_sync_records_job (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sync_errors (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    `row_number` INT UNSIGNED NULL,
    field_name VARCHAR(64) NULL,
    error_code VARCHAR(64) NOT NULL,
    error_message VARCHAR(512) NOT NULL,
    raw_row JSON NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_sync_errors_job_row (job_id, `row_number`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
