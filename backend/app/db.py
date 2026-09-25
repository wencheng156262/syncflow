"""MySQL data-access helpers for SyncFlow.

The API and Worker both use this module so connection settings and SQL access
stay in one place.  Keeping the queries here also makes the HTTP layer easier
to test without coupling it to cursor management.
"""

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


def mark_job_failed(job_id: str, error_code: str, message: str) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sync_jobs
                SET status = 'FAILED', last_error_code = %s,
                    last_error_message = %s, finished_at = UTC_TIMESTAMP(3)
                WHERE id = %s
                """,
                (error_code, message, job_id),
            )

