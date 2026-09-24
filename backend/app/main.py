import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import redis
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.api")

app = FastAPI(title="SyncFlow API", version="0.1.0")

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "syncflow")
MYSQL_USER = os.getenv("MYSQL_USER", "syncflow")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "syncflow123")
REDIS_HOST, REDIS_PORT = os.getenv("REDIS_ADDR", "localhost:6379").split(":", 1)
REDIS_PORT = int(REDIS_PORT)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
MAX_UPLOAD_FILE_SIZE_MB = int(os.getenv("MAX_UPLOAD_FILE_SIZE_MB", "10"))
MAX_UPLOAD_FILE_SIZE = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
ALLOWED_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "PARTIAL_SUCCESS",
    "FAILED",
    "CANCELED",
}

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    )


def api_error(status_code: int, code: str, message: str, details: Optional[List[Any]] = None):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or []},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    detail = exc.detail
    error = detail if isinstance(detail, dict) and "code" in detail else {
        "code": "HTTP_ERROR",
        "message": str(detail),
        "details": [],
    }
    return JSONResponse(status_code=exc.status_code, content={"error": error})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "请求参数不合法",
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(_: Request, exc: Exception):
    logger.exception("Unhandled API error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务内部错误",
                "details": [],
            }
        },
    )


def serialize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "name": job["name"],
        "status": job["status"],
        "source_file_name": job["source_file_name"],
        "total_records": job["total_records"],
        "success_records": job["success_records"],
        "failed_records": job["failed_records"],
        "retry_count": job["retry_count"],
        "last_error_code": job["last_error_code"],
        "last_error_message": job["last_error_message"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


def save_upload(file: UploadFile) -> Tuple[str, str, str]:
    original_name = Path(file.filename or "").name
    if not original_name or not original_name.lower().endswith(".csv"):
        api_error(400, "INVALID_FILE_EXTENSION", "只支持 CSV 文件")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOAD_DIR / (str(uuid.uuid4()) + ".csv")
    digest = hashlib.sha256()
    total_size = 0

    try:
        with stored_path.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_FILE_SIZE:
                    api_error(
                        400,
                        "FILE_TOO_LARGE",
                        "文件超过大小限制",
                        [{"max_size_mb": MAX_UPLOAD_FILE_SIZE_MB}],
                    )
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    return original_name, str(stored_path), digest.hexdigest()


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


def get_job_or_error(job_id: str) -> Dict[str, Any]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, status, source_file_name, total_records,
                       success_records, failed_records, retry_count,
                       last_error_code, last_error_message, created_at,
                       started_at, finished_at
                FROM sync_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            job = cursor.fetchone()
    finally:
        connection.close()

    if job is None:
        api_error(404, "JOB_NOT_FOUND", "任务不存在")
    return job


def mark_job_failed(job_id: str, error_code: str, message: str):
    connection = get_db_connection()
    try:
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
        connection.commit()
    finally:
        connection.close()


@app.get("/")
def root():
    return {"data": {"service": "SyncFlow API", "status": "running"}, "meta": {}}


@app.get("/healthz")
def healthz():
    return {"data": {"status": "ok"}, "meta": {}}


@app.get("/readyz")
def readyz():
    try:
        redis_client.ping()
        connection = get_db_connection()
        connection.close()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        api_error(503, "DEPENDENCY_UNAVAILABLE", "数据库或 Redis 暂不可用")
    return {"data": {"status": "ready"}, "meta": {}}


@app.post("/api/v1/jobs", status_code=201)
def create_job(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    original_name = Path(file.filename or "").name
    if not original_name.lower().endswith(".csv"):
        api_error(400, "INVALID_FILE_EXTENSION", "只支持 CSV 文件")

    if idempotency_key:
        existing = get_job_by_idempotency_key(idempotency_key)
        if existing:
            return {
                "data": serialize_job(get_job_or_error(existing["id"])),
                "meta": {"idempotent": True},
            }

    source_file_name, stored_file_path, file_sha256 = save_upload(file)
    job_id = str(uuid.uuid4())
    job_name = (name or Path(source_file_name).stem or "CSV 同步任务").strip()[:128]

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sync_jobs
                    (id, name, status, source_file_name, stored_file_path,
                     file_sha256, idempotency_key)
                VALUES (%s, %s, 'PENDING', %s, %s, %s, %s)
                """,
                (job_id, job_name, source_file_name, stored_file_path, file_sha256, idempotency_key),
            )
        connection.commit()
    except pymysql.err.IntegrityError:
        connection.rollback()
        Path(stored_file_path).unlink(missing_ok=True)
        if idempotency_key:
            existing = get_job_by_idempotency_key(idempotency_key)
            if existing:
                return {
                    "data": serialize_job(get_job_or_error(existing["id"])),
                    "meta": {"idempotent": True},
                }
        api_error(500, "INTERNAL_ERROR", "任务创建失败")
    finally:
        connection.close()

    try:
        redis_client.lpush(QUEUE_NAME, job_id)
    except Exception:
        mark_job_failed(job_id, "QUEUE_UNAVAILABLE", "任务队列暂不可用")
        api_error(503, "QUEUE_UNAVAILABLE", "任务队列暂不可用")

    return {"data": serialize_job(get_job_or_error(job_id)), "meta": {}}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    return {"data": serialize_job(get_job_or_error(job_id)), "meta": {}}


@app.get("/api/v1/jobs")
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    if status and status not in ALLOWED_STATUSES:
        api_error(400, "INVALID_REQUEST", "状态筛选条件不合法")

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            where = ""
            params: List[Any] = []
            if status:
                where = "WHERE status = %s"
                params.append(status)
            cursor.execute("SELECT COUNT(*) AS total FROM sync_jobs " + where, params)
            total = cursor.fetchone()["total"]
            offset = (page - 1) * page_size
            cursor.execute(
                """
                SELECT id, name, status, source_file_name, total_records,
                       success_records, failed_records, retry_count,
                       last_error_code, last_error_message, created_at,
                       started_at, finished_at
                FROM sync_jobs
                """
                + where
                + " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                params + [page_size, offset],
            )
            jobs = cursor.fetchall()
    finally:
        connection.close()

    return {
        "data": [serialize_job(job) for job in jobs],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }
