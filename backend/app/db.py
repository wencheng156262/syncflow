"""MySQL data-access helpers for SyncFlow.

The API and Worker both use this module so connection settings and SQL access
stay in one place.  Keeping the queries here also makes the HTTP layer easier
to test without coupling it to cursor management.
"""

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence

import pymysql


MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "syncflow")
MYSQL_USER = os.getenv("MYSQL_USER", "syncflow")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "syncflow123")

JOB_COLUMNS = """
    id, name, status, source_file_name, total_records,
    success_records, failed_records, retry_count,
    last_error_code, last_error_message, created_at,
    started_at, finished_at
"""
PROCESSING_JOB_COLUMNS = JOB_COLUMNS + ", stored_file_path"
NON_TERMINAL_STATUSES = ("PENDING", "RUNNING", "RETRYING", "CANCELING")


def get_db_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


@contextmanager
def transaction() -> Iterator[Any]:
    connection = get_db_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {JOB_COLUMNS} FROM sync_jobs WHERE id = %s", (job_id,))
            return cursor.fetchone()
    finally:
        connection.close()


def get_job_by_idempotency_key(idempotency_key: str) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM sync_jobs WHERE idempotency_key = %s",
                (idempotency_key[:128],),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def get_job_for_processing(job_id: str) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {PROCESSING_JOB_COLUMNS} FROM sync_jobs WHERE id = %s",
                (job_id,),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def insert_job(
    job_id: str,
    name: str,
    source_file_name: str,
    stored_file_path: str,
    file_sha256: str,
    idempotency_key: Optional[str],
) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sync_jobs
                    (id, name, status, source_file_name, stored_file_path,
                     file_sha256, idempotency_key)
                VALUES (%s, %s, 'PENDING', %s, %s, %s, %s)
                """,
                (
                    job_id,
                    name,
                    source_file_name,
                    stored_file_path,
                    file_sha256,
                    idempotency_key[:128] if idempotency_key else None,
                ),
            )


def list_jobs(
    page: int,
    page_size: int,
    status: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], int]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            where = ""
            params: List[Any] = []
            if status:
                where = "WHERE status = %s"
                params.append(status)

            cursor.execute("SELECT COUNT(*) AS total FROM sync_jobs " + where, params)
            total = int(cursor.fetchone()["total"])

            offset = (page - 1) * page_size
            cursor.execute(
                f"""
                SELECT {JOB_COLUMNS}
                FROM sync_jobs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            return cursor.fetchall(), total
    finally:
        connection.close()


def update_job_status(job_id: str, status: str) -> int:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            if status == "RUNNING":
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'RUNNING',
                        started_at = COALESCE(started_at, UTC_TIMESTAMP(3))
                    WHERE id = %s AND status = 'PENDING'
                    """,
                    (job_id,),
                )
            elif status == "SUCCESS":
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'SUCCESS', finished_at = UTC_TIMESTAMP(3)
                    WHERE id = %s AND status = 'RUNNING'
                    """,
                    (job_id,),
                )
            else:
                cursor.execute(
                    "UPDATE sync_jobs SET status = %s WHERE id = %s",
                    (status, job_id),
                )
            affected = cursor.rowcount
        connection.commit()
        return affected
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, status, retry_count FROM sync_jobs WHERE id = %s",
                (job_id,),
            )
            return cursor.fetchone()
    finally:
        connection.close()


def transition_job(
    job_id: str,
    from_statuses: Sequence[str],
    to_status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    increment_retry: bool = False,
) -> bool:
    if not from_statuses:
        return False

    placeholders = ", ".join(["%s"] * len(from_statuses))
    assignments = ["status = %s", "updated_at = UTC_TIMESTAMP(3)"]
    params: List[Any] = [to_status]
    if to_status == "RUNNING":
        assignments.append("started_at = COALESCE(started_at, UTC_TIMESTAMP(3))")
    if to_status in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELED"}:
        assignments.append("finished_at = UTC_TIMESTAMP(3)")
    if error_code is not None:
        assignments.append("last_error_code = %s")
        params.append(error_code)
    if error_message is not None:
        assignments.append("last_error_message = %s")
        params.append(error_message)
    if increment_retry:
        assignments.append("retry_count = retry_count + 1")

    params.extend([job_id, *from_statuses])
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE sync_jobs
                SET {", ".join(assignments)}
                WHERE id = %s AND status IN ({placeholders})
                """,
                params,
            )
            return cursor.rowcount == 1


def request_job_cancel(job_id: str) -> Optional[str]:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM sync_jobs WHERE id = %s FOR UPDATE",
                (job_id,),
            )
            job = cursor.fetchone()
            if job is None:
                return None

            current_status = job["status"]
            if current_status in {"PENDING", "RETRYING"}:
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'CANCELED',
                        last_error_code = 'CANCELED_BY_USER',
                        last_error_message = '任务已被用户取消',
                        finished_at = UTC_TIMESTAMP(3),
                        updated_at = UTC_TIMESTAMP(3)
                    WHERE id = %s
                    """,
                    (job_id,),
                )
            elif current_status == "RUNNING":
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = 'CANCELING',
                        last_error_code = 'CANCEL_REQUESTED',
                        last_error_message = '已请求取消，等待 Worker 安全停止',
                        updated_at = UTC_TIMESTAMP(3)
                    WHERE id = %s AND status = 'RUNNING'
                    """,
                    (job_id,),
                )
            return current_status


def mark_job_pending(job_id: str) -> bool:
    return transition_job(job_id, ("RETRYING",), "PENDING")


def mark_job_retrying(job_id: str, error_code: str, message: str) -> bool:
    return transition_job(
        job_id,
        ("RUNNING",),
        "RETRYING",
        error_code=error_code,
        error_message=message,
        increment_retry=True,
    )


def mark_job_canceled(job_id: str) -> bool:
    return transition_job(
        job_id,
        ("CANCELING",),
        "CANCELED",
        error_code="CANCELED_BY_USER",
        error_message="任务已被用户取消",
    )


def list_stale_running_jobs(timeout_seconds: int) -> List[Dict[str, Any]]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, retry_count
                FROM sync_jobs
                WHERE status = 'RUNNING'
                  AND updated_at < UTC_TIMESTAMP(3) - INTERVAL %s SECOND
                ORDER BY updated_at ASC
                """,
                (timeout_seconds,),
            )
            return cursor.fetchall()
    finally:
        connection.close()


def mark_job_failed(job_id: str, error_code: str, message: str) -> None:
    transition_job(
        job_id,
        NON_TERMINAL_STATUSES,
        "FAILED",
        error_code=error_code,
        error_message=message,
    )


def mark_job_running(job_id: str) -> bool:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sync_jobs
                SET status = 'RUNNING',
                    started_at = COALESCE(started_at, UTC_TIMESTAMP(3))
                WHERE id = %s AND status = 'PENDING'
                """,
                (job_id,),
            )
            return cursor.rowcount == 1


def list_job_errors(
    job_id: str,
    page: int,
    page_size: int,
) -> tuple[List[Dict[str, Any]], int]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM sync_errors WHERE job_id = %s",
                (job_id,),
            )
            total = int(cursor.fetchone()["total"])
            offset = (page - 1) * page_size
            cursor.execute(
                """
                SELECT job_id, `row_number`, field_name, error_code,
                       error_message, raw_row, created_at
                FROM sync_errors
                WHERE job_id = %s
                ORDER BY `row_number` IS NULL ASC, `row_number` ASC, id ASC
                LIMIT %s OFFSET %s
                """,
                (job_id, page_size, offset),
            )
            return cursor.fetchall(), total
    finally:
        connection.close()


def clear_job_result(job_id: str) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM sync_records WHERE job_id = %s", (job_id,))
            cursor.execute("DELETE FROM sync_errors WHERE job_id = %s", (job_id,))

def insert_records_batch(job_id: str, records: Sequence[Dict[str, Any]]) -> None:
    if not records:
        return
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO sync_records
                    (job_id, external_id, name, amount, record_date)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        job_id,
                        record["external_id"],
                        record["name"],
                        record["amount"],
                        record["record_date"],
                    )
                    for record in records
                ],
            )


def insert_errors_batch(job_id: str, errors: Sequence[Dict[str, Any]]) -> None:
    if not errors:
        return
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO sync_errors
                    (job_id, `row_number`, field_name, error_code,
                     error_message, raw_row)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        job_id,
                        error.get("row_number"),
                        error.get("field_name"),
                        error["error_code"],
                        error["error_message"],
                        json.dumps(error.get("raw_row"), ensure_ascii=False) if error.get("raw_row") is not None else None,
                    )
                    for error in errors
                ],
            )


def finalize_job_result(
    job_id: str,
    total_records: int,
    success_records: int,
    failed_records: int,
    last_error: Optional[Dict[str, Any]] = None,
) -> bool:
    if failed_records == 0:
        final_status = "SUCCESS"
    elif success_records > 0:
        final_status = "PARTIAL_SUCCESS"
    else:
        final_status = "FAILED"

    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sync_jobs
                SET total_records = %s,
                    success_records = %s,
                    failed_records = %s,
                    status = %s,
                    last_error_code = %s,
                    last_error_message = %s,
                    finished_at = UTC_TIMESTAMP(3)
                WHERE id = %s AND status = 'RUNNING'
                """,
                (
                    total_records,
                    success_records,
                    failed_records,
                    final_status,
                    last_error["error_code"] if last_error else None,
                    last_error["error_message"] if last_error else None,
                    job_id,
                ),
            )
            return cursor.rowcount == 1


def write_file_error(job_id: str, error_code: str, error_message: str) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM sync_errors WHERE job_id = %s", (job_id,))
            cursor.execute(
                """
                INSERT INTO sync_errors
                    (job_id, `row_number`, field_name, error_code, error_message)
                VALUES (%s, NULL, NULL, %s, %s)
                """,
                (job_id, error_code, error_message),
            )
            cursor.execute(
                """
                UPDATE sync_jobs
                SET total_records = 0,
                    success_records = 0,
                    failed_records = 0,
                    status = 'FAILED',
                    last_error_code = %s,
                    last_error_message = %s,
                    finished_at = UTC_TIMESTAMP(3)
                WHERE id = %s AND status = 'RUNNING'
                """,
                (error_code, error_message, job_id),
            )
