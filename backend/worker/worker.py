import logging
import os
import time

import redis

from app.csv_processing import parse_csv_file
from app.db import (
    get_job_for_processing,
    mark_job_failed,
    mark_job_running,
    write_file_error,
    write_job_result,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.worker")

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
REDIS_HOST, REDIS_PORT = os.getenv("REDIS_ADDR", "localhost:6379").rsplit(":", 1)
REDIS_PORT = int(REDIS_PORT)
MAX_RECORDS_PER_JOB = int(os.getenv("MAX_RECORDS_PER_JOB", "10000"))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def process_job(job_id: str) -> None:
    job = get_job_for_processing(job_id)
    if job is None:
        logger.error("job_id=%s not found", job_id)
        return

    if not mark_job_running(job_id):
        logger.info("job_id=%s skipped because it is no longer PENDING", job_id)
        return
    logger.info("job_id=%s status=RUNNING", job_id)

    parsed = parse_csv_file(job["stored_file_path"], max_records=MAX_RECORDS_PER_JOB)
    if parsed.file_error:
        error = parsed.file_error
        write_file_error(job_id, error["error_code"], error["error_message"])
        logger.error("job_id=%s file_error=%s", job_id, error["error_code"])
        return

    failed_row_numbers = {error["row_number"] for error in parsed.errors}
    try:
        write_job_result(
            job_id=job_id,
            total_records=parsed.total_records,
            success_records=len(parsed.records),
            failed_records=len(failed_row_numbers),
            records=parsed.records,
            errors=parsed.errors,
        )
    except Exception as exc:
        logger.exception("job_id=%s failed while writing result", job_id)
        mark_job_failed(job_id, "PROCESSING_ERROR", f"处理结果写入失败：{exc}")
        return

    final_status = "SUCCESS" if not failed_row_numbers else "PARTIAL_SUCCESS" if parsed.records else "FAILED"
    logger.info(
        "job_id=%s progress=%s/%s success=%s failed=%s status=%s",
        job_id,
        parsed.total_records,
        parsed.total_records,
        len(parsed.records),
        len(failed_row_numbers),
        final_status,
    )


def main() -> None:
    logger.info("SyncFlow Worker started")
    logger.info("Waiting for jobs from Redis queue: %s", QUEUE_NAME)

    while True:
        job_id = None
        try:
            _, job_id = redis_client.brpop(QUEUE_NAME)
            logger.info("job_id=%s received", job_id)
            process_job(job_id)
        except Exception:
            logger.exception("Worker loop failed; retrying in 2 seconds")
            if job_id:
                try:
                    mark_job_failed(job_id, "PROCESSING_ERROR", "Worker 处理任务时发生未知错误")
                except Exception:
                    logger.exception("job_id=%s could not be marked FAILED", job_id)
            time.sleep(2)


if __name__ == "__main__":
    main()
