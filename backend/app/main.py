import hashlib
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

import redis
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.requests import Request

from app.db import (
    get_db_connection,
    get_job,
    get_job_by_idempotency_key,
    insert_job,
    list_jobs as db_list_jobs,
    mark_job_failed,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("syncflow.api")

app = FastAPI(
    title="SyncFlow API",
    version="0.2.0",
    description="CSV 数据同步任务管理 API。",
)

QUEUE_NAME = os.getenv("QUEUE_NAME", "syncflow:jobs")
REDIS_ADDR = os.getenv("REDIS_ADDR", "localhost:6379")
REDIS_HOST, REDIS_PORT = REDIS_ADDR.rsplit(":", 1)
REDIS_PORT = int(REDIS_PORT)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
MAX_UPLOAD_FILE_SIZE_MB = int(os.getenv("MAX_UPLOAD_FILE_SIZE_MB", "10"))
MAX_UPLOAD_FILE_SIZE = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
ALLOWED_STATUSES = {"PENDING", "RUNNING", "SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELED"}

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


class JobResponse(BaseModel):
    id: str
    name: str
    status: str
    source_file_name: str
    total_records: int
    success_records: int
    failed_records: int
    retry_count: int
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


ResponseData = TypeVar("ResponseData")


class ApiResponse(BaseModel, Generic[ResponseData]):
    data: ResponseData
    meta: Dict[str, Any]


def api_error(
    status_code: int,
    code: str,
    message: str,
    details: Optional[List[Any]] = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or []},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    detail = exc.detail
    error = (
        detail
        if isinstance(detail, dict) and "code" in detail
        else {"code": "HTTP_ERROR", "message": str(detail), "details": []}
    )
    return JSONResponse(status_code=exc.status_code, content={"error": error})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    details = [
        {"loc": list(error.get("loc", [])), "msg": error.get("msg", ""), "type": error.get("type", "")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "请求参数不合法",
                "details": details,
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


def format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    # MySQL DATETIME does not carry timezone metadata; all writes are UTC.
    return value.isoformat(timespec="milliseconds") + "Z"


def serialize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "name": job["name"],
        "status": job["status"],
        "source_file_name": job["source_file_name"],
        "total_records": int(job["total_records"] or 0),
        "success_records": int(job["success_records"] or 0),
        "failed_records": int(job["failed_records"] or 0),
        "retry_count": int(job["retry_count"] or 0),
        "last_error_code": job["last_error_code"],
        "last_error_message": job["last_error_message"],
        "created_at": format_datetime(job["created_at"]),
        "started_at": format_datetime(job["started_at"]),
        "finished_at": format_datetime(job["finished_at"]),
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


def get_job_or_error(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        api_error(404, "JOB_NOT_FOUND", "任务不存在")
    return job


@app.get("/", response_model=ApiResponse[Dict[str, str]], tags=["system"])
def root():
    return {"data": {"service": "SyncFlow API", "status": "running"}, "meta": {}}


@app.get("/healthz", response_model=ApiResponse[Dict[str, str]], tags=["system"])
def healthz():
    return {"data": {"status": "ok"}, "meta": {}}


@app.get("/readyz", response_model=ApiResponse[Dict[str, str]], tags=["system"])
def readyz():
    try:
        redis_client.ping()
        connection = get_db_connection()
        connection.close()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        api_error(503, "DEPENDENCY_UNAVAILABLE", "数据库或 Redis 暂不可用")
    return {"data": {"status": "ready"}, "meta": {}}


@app.post("/api/v1/jobs", status_code=201, response_model=ApiResponse[JobResponse], tags=["jobs"])
def create_job(
    file: UploadFile = File(..., description="CSV 文件"),
    name: Optional[str] = Form(None, max_length=128, description="任务名称"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
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

    try:
        insert_job(
            job_id,
            job_name,
            source_file_name,
            stored_file_path,
            file_sha256,
            idempotency_key,
        )
    except Exception as exc:
        Path(stored_file_path).unlink(missing_ok=True)
        if getattr(exc, "args", [None])[0] == 1062 and idempotency_key:
            existing = get_job_by_idempotency_key(idempotency_key)
            if existing:
                return {
                    "data": serialize_job(get_job_or_error(existing["id"])),
                    "meta": {"idempotent": True},
                }
        logger.exception("Failed to insert job %s", job_id)
        api_error(500, "INTERNAL_ERROR", "任务创建失败")

    try:
        redis_client.lpush(QUEUE_NAME, job_id)
    except Exception:
        mark_job_failed(job_id, "QUEUE_UNAVAILABLE", "任务队列暂不可用")
        api_error(503, "QUEUE_UNAVAILABLE", "任务队列暂不可用")

    return {"data": serialize_job(get_job_or_error(job_id)), "meta": {}}


@app.get("/api/v1/jobs/{job_id}", response_model=ApiResponse[JobResponse], tags=["jobs"])
def get_job_detail(job_id: str):
    return {"data": serialize_job(get_job_or_error(job_id)), "meta": {}}


@app.get("/api/v1/jobs", response_model=ApiResponse[List[JobResponse]], tags=["jobs"])
def list_job_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    if status and status not in ALLOWED_STATUSES:
        api_error(400, "INVALID_REQUEST", "状态筛选条件不合法")

    jobs, total = db_list_jobs(page=page, page_size=page_size, status=status)
    return {
        "data": [serialize_job(job) for job in jobs],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }
