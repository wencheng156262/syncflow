"""Concurrent Redis worker with retries, cancellation and graceful shutdown."""

import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, Optional, Tuple

import redis

from app.csv_processing import parse_csv_file
from app.db import (
    clear_job_result,
    finalize_job_result,
    get_job_for_processing,
    get_job_status,
    finish_job_attempt,
    insert_errors_batch,
    insert_records_batch,
    list_stale_running_jobs,
    mark_job_canceled,
    mark_job_failed,
    mark_job_pending,
    mark_job_retrying,
    mark_job_running,
    start_job_attempt,
    write_file_error,
)
from app.retry_policy import backoff_seconds, is_retryable_error, parse_backoff_schedule

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.worker")

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
REDIS_HOST, REDIS_PORT = os.getenv("REDIS_ADDR", "localhost:6379").rsplit(":", 1)
REDIS_PORT = int(REDIS_PORT)
MAX_RECORDS_PER_JOB = int(os.getenv("MAX_RECORDS_PER_JOB", "10000"))
BATCH_SIZE = 500
MAX_JOB_ATTEMPTS = max(int(os.getenv("MAX_JOB_ATTEMPTS", os.getenv("MAX_JOB_RETRIES", "3"))), 1)
RETRY_BACKOFF_SECONDS = parse_backoff_schedule(os.getenv("RETRY_BACKOFF_SECONDS", "5,30,120"))
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "300"))
WORKER_SHUTDOWN_TIMEOUT_SECONDS = int(os.getenv("WORKER_SHUTDOWN_TIMEOUT_SECONDS", "30"))
DEFAULT_CONCURRENCY = min(max(os.cpu_count() or 2, 2), 4)
WORKER_CONCURRENCY = max(int(os.getenv("WORKER_CONCURRENCY", str(DEFAULT_CONCURRENCY))), 1)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


class JobControlError(Exception):
    """Base class for an intentional stop of one job attempt."""


class JobCanceled(JobControlError):
    """Signal that a user cancellation should stop the current attempt."""

    pass


class JobTimedOut(JobControlError):
    """Signal that the current attempt exceeded its execution deadline."""

    pass


class WorkerShuttingDown(JobControlError):
    """Signal that shutdown should return the job to the queue safely."""

    pass


class RetryableProcessingError(Exception):
    """Carry a stable error code for a transient processing failure."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def parse_queue_message(raw_message: str) -> Tuple[str, int]:
    """Read the Week 4 JSON envelope while accepting old raw job IDs."""

    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        return raw_message, 1
    if isinstance(payload, dict) and payload.get("job_id"):
        return str(payload["job_id"]), max(int(payload.get("attempt_no", 1)), 1)
    return raw_message, 1


def publish_job(job_id: str, attempt_no: int) -> None:
    redis_client.lpush(
        QUEUE_NAME,
        json.dumps({"job_id": job_id, "attempt_no": attempt_no}, ensure_ascii=False),
    )


def _check_job_control(job_id: str, started_at: float, stop_event: threading.Event) -> None:
    if stop_event.is_set():
        raise WorkerShuttingDown("Worker 正在优雅停止")
    if time.monotonic() - started_at >= JOB_TIMEOUT_SECONDS:
        raise JobTimedOut(f"任务执行超过 {JOB_TIMEOUT_SECONDS} 秒")

    job = get_job_status(job_id)
    if job is None:
        raise JobControlError("任务不存在")
    if job["status"] == "CANCELING":
        raise JobCanceled("任务收到取消请求")
    if job["status"] != "RUNNING":
        raise JobControlError(f"任务当前状态为 {job['status']}")


def _schedule_retry(job_id: str, attempt_no: int, error_code: str, message: str) -> None:
    """Retry transient failures with backoff, or finish the job as FAILED."""
    current = get_job_status(job_id)
    if current is None or current["status"] != "RUNNING":
        return

    retryable = is_retryable_error(error_code)
    if not retryable or attempt_no >= MAX_JOB_ATTEMPTS:
        mark_job_failed(job_id, error_code, message)
        finish_job_attempt(job_id, attempt_no, "FAILED", error_code, message)
        logger.error("job_id=%s status=FAILED retryable=%s attempt=%s", job_id, retryable, attempt_no)
        return

    if not mark_job_retrying(job_id, error_code, message):
        return

    finish_job_attempt(job_id, attempt_no, "RETRYING", error_code, message)
    delay = backoff_seconds(attempt_no, RETRY_BACKOFF_SECONDS)
    logger.warning("job_id=%s status=RETRYING backoff=%ss next_attempt=%s", job_id, delay, attempt_no + 1)
    if delay:
        time.sleep(delay)
    retry_state = get_job_status(job_id)
    if retry_state is None or retry_state["status"] != "RETRYING":
        logger.info("job_id=%s retry canceled while waiting", job_id)
        return
    if not mark_job_pending(job_id):
        logger.warning("job_id=%s could not transition RETRYING -> PENDING", job_id)
        return
    try:
        publish_job(job_id, attempt_no + 1)
    except Exception:
        logger.exception("job_id=%s retry enqueue failed", job_id)
        mark_job_failed(job_id, "QUEUE_UNAVAILABLE", "重试任务重新入队失败")
        return

    logger.warning("job_id=%s status=RETRYING -> PENDING attempt=%s", job_id, attempt_no)


def recover_stale_jobs() -> None:
    """Requeue RUNNING jobs left behind by a previous Worker process."""

    for job in list_stale_running_jobs(JOB_TIMEOUT_SECONDS):
        job_id = job["id"]
        logger.warning("job_id=%s stale RUNNING job detected; recovering", job_id)
        _schedule_retry(job_id, max(int(job["retry_count"] or 0) + 1, 1), "WORKER_RESTARTED", "Worker 重启后恢复超时任务")


def process_job(job_id: str, attempt_no: int = 1, stop_event: Optional[threading.Event] = None) -> None:
    stop_event = stop_event or threading.Event()
    job = get_job_for_processing(job_id)
    if job is None:
        logger.error("job_id=%s not found", job_id)
        return

    if not mark_job_running(job_id):
        logger.info("job_id=%s skipped because it is no longer PENDING", job_id)
        return

    started_at = time.monotonic()
    start_job_attempt(job_id, max(attempt_no, 1))
    attempt_no = max(attempt_no, 1)
    logger.info("job_id=%s status=RUNNING attempt=%s", job_id, attempt_no)

    try:
        _check_job_control(job_id, started_at, stop_event)
        parsed = parse_csv_file(job["stored_file_path"], max_records=MAX_RECORDS_PER_JOB)
        _check_job_control(job_id, started_at, stop_event)

        if parsed.file_error:
            error = parsed.file_error
            write_file_error(job_id, error["error_code"], error["error_message"])
            finish_job_attempt(job_id, attempt_no, "FAILED", error["error_code"], error["error_message"])
            logger.error("job_id=%s file_error=%s", job_id, error["error_code"])
            return

        failed_row_numbers = {error["row_number"] for error in parsed.errors}
        clear_job_result(job_id)
        success_records = 0
        all_errors = list(parsed.errors)

        for start in range(0, len(parsed.records), BATCH_SIZE):
            _check_job_control(job_id, started_at, stop_event)
            batch = parsed.records[start : start + BATCH_SIZE]
            try:
                insert_records_batch(job_id, batch)
            except Exception as exc:
                logger.exception(
                    "job_id=%s record_batch_failed start=%s size=%s",
                    job_id,
                    start,
                    len(batch),
                )
                raise RetryableProcessingError("BATCH_WRITE_FAILED", f"成功记录批量写入失败：{exc}") from exc
            else:
                success_records += len(batch)

            logger.info(
                "job_id=%s progress=%s/%s success=%s failed=%s",
                job_id,
                success_records + len(failed_row_numbers),
                parsed.total_records,
                success_records,
                len(failed_row_numbers),
            )

        for start in range(0, len(parsed.errors), BATCH_SIZE):
            _check_job_control(job_id, started_at, stop_event)
            batch = parsed.errors[start : start + BATCH_SIZE]
            try:
                insert_errors_batch(job_id, batch)
            except Exception as exc:
                logger.exception(
                    "job_id=%s error_batch_failed start=%s size=%s",
                    job_id,
                    start,
                    len(batch),
                )
                raise RetryableProcessingError("BATCH_WRITE_FAILED", f"错误记录批量写入失败：{exc}") from exc

        finalized = finalize_job_result(
            job_id=job_id,
            total_records=parsed.total_records,
            success_records=success_records,
            failed_records=len(failed_row_numbers),
            last_error=all_errors[0] if all_errors else None,
        )
        if not finalized:
            if mark_job_canceled(job_id):
                finish_job_attempt(job_id, attempt_no, "CANCELED", "JOB_CANCELED", "任务已被用户取消")
                logger.info("job_id=%s status=CANCELED after concurrent cancel request", job_id)
            return
        final_status = "SUCCESS" if not failed_row_numbers else "PARTIAL_SUCCESS" if success_records else "FAILED"
        finish_job_attempt(job_id, attempt_no, final_status)
        logger.info(
            "job_id=%s progress=%s/%s success=%s failed=%s status=%s",
            job_id,
            parsed.total_records,
            parsed.total_records,
            success_records,
            len(failed_row_numbers),
            final_status,
        )
    except JobCanceled as exc:
        if mark_job_canceled(job_id):
            finish_job_attempt(job_id, attempt_no, "CANCELED", "JOB_CANCELED", str(exc))
            logger.info("job_id=%s status=CANCELED reason=%s", job_id, exc)
    except (JobTimedOut, WorkerShuttingDown) as exc:
        code = "JOB_TIMEOUT" if isinstance(exc, JobTimedOut) else "WORKER_SHUTDOWN"
        _schedule_retry(job_id, attempt_no, code, str(exc))
    except RetryableProcessingError as exc:
        _schedule_retry(job_id, attempt_no, exc.error_code, str(exc))
    except JobControlError as exc:
        mark_job_failed(job_id, "JOB_CONTROL_ERROR", str(exc))
        finish_job_attempt(job_id, attempt_no, "FAILED", "JOB_CONTROL_ERROR", str(exc))
        logger.warning("job_id=%s stopped without retry: %s", job_id, exc)
    except Exception as exc:
        logger.exception("job_id=%s failed during processing", job_id)
        _schedule_retry(job_id, attempt_no, "PROCESSING_ERROR", f"处理任务时发生错误：{exc}")


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def request_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal=%s; stop consuming new jobs", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


def main() -> None:
    logger.info(
        "SyncFlow Worker started concurrency=%s timeout=%ss shutdown_timeout=%ss",
        WORKER_CONCURRENCY,
        JOB_TIMEOUT_SECONDS,
        WORKER_SHUTDOWN_TIMEOUT_SECONDS,
    )
    recover_stale_jobs()
    logger.info("Waiting for jobs from Redis queue: %s", QUEUE_NAME)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    active: Dict[str, Future[None]] = {}
    executor = ThreadPoolExecutor(max_workers=WORKER_CONCURRENCY, thread_name_prefix="syncflow-worker")

    try:
        while not stop_event.is_set():
            try:
                item = redis_client.brpop(QUEUE_NAME, timeout=1)
            except Exception:
                logger.exception("Worker queue read failed; retrying in 2 seconds")
                time.sleep(2)
                continue
            if not item:
                continue

            job_id, attempt_no = parse_queue_message(item[1])
            future = executor.submit(process_job, job_id, attempt_no, stop_event)
            active[job_id] = future
            active = {key: value for key, value in active.items() if not value.done()}
    finally:
        stop_event.set()
        logger.info("Worker stopping; waiting up to %ss for active jobs", WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        deadline = time.monotonic() + WORKER_SHUTDOWN_TIMEOUT_SECONDS
        while active and time.monotonic() < deadline:
            active = {key: value for key, value in active.items() if not value.done()}
            if active:
                time.sleep(0.1)

        for job_id, future in list(active.items()):
            if not future.done():
                _schedule_retry(job_id, 1, "WORKER_SHUTDOWN_TIMEOUT", "Worker 优雅停止超时，任务已重新入队")

        executor.shutdown(wait=True, cancel_futures=False)
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
