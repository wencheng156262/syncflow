-- Week 5 records every execution attempt and moves the 24-hour idempotency
-- ownership into a dedicated table so an expired key can be reused safely.
CREATE TABLE IF NOT EXISTS job_attempts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    attempt_no TINYINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64) NULL,
    error_message VARCHAR(512) NULL,
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    finished_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_job_attempts_job_attempt (job_id, attempt_no),
    KEY idx_job_attempts_job (job_id, attempt_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS job_idempotency_keys (
    idempotency_key VARCHAR(128) NOT NULL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    expires_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_job_idempotency_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The dedicated table is now authoritative for the 24-hour key window.
-- Keep the original column on sync_jobs for observability, but do not enforce
-- a lifetime-wide unique constraint there.
SET @drop_sync_job_key_index = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'sync_jobs'
              AND index_name = 'uk_sync_jobs_idempotency_key'
        ),
        'ALTER TABLE sync_jobs DROP INDEX uk_sync_jobs_idempotency_key',
        'SELECT 1'
    )
);
PREPARE drop_sync_job_key_index FROM @drop_sync_job_key_index;
EXECUTE drop_sync_job_key_index;
DEALLOCATE PREPARE drop_sync_job_key_index;
