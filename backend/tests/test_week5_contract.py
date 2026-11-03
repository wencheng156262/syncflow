from datetime import datetime

from fastapi.testclient import TestClient

import app.main as main
from app.db import IdempotencyConflictError
from app.main import app
from app.retry_policy import backoff_seconds, is_retryable_error, parse_backoff_schedule


client = TestClient(app)


def test_retry_policy_distinguishes_transient_and_validation_errors():
    assert is_retryable_error("BATCH_WRITE_FAILED") is True
    assert is_retryable_error("AMOUNT_INVALID") is False
    assert backoff_seconds(1) == 5
    assert backoff_seconds(2) == 30
    assert backoff_seconds(3) == 120
    assert backoff_seconds(4) == 120
    assert parse_backoff_schedule("1, 2, 3") == (1, 2, 3)


def test_retry_endpoint_requeues_failed_job(monkeypatch):
    job = {
        "id": "job-1",
        "name": "demo",
        "status": "PENDING",
        "source_file_name": "demo.csv",
        "total_records": 0,
        "success_records": 0,
        "failed_records": 0,
        "retry_count": 0,
        "last_error_code": None,
        "last_error_message": None,
        "created_at": datetime(2026, 1, 1),
        "started_at": None,
        "finished_at": None,
    }
    monkeypatch.setattr(main, "get_job", lambda _: job)
    monkeypatch.setattr(main, "prepare_job_retry", lambda _: {"status": "FAILED", "attempt_no": 2})
    published = []
    monkeypatch.setattr(main, "enqueue_job", lambda job_id, attempt_no: published.append((job_id, attempt_no)))

    response = client.post("/api/v1/jobs/job-1/retry")

    assert response.status_code == 202
    assert published == [("job-1", 2)]
    assert response.json()["meta"]["manual_retry"] is True


def test_retry_endpoint_rejects_non_failed_job(monkeypatch):
    monkeypatch.setattr(main, "get_job", lambda _: {"id": "job-1", "status": "SUCCESS"})
    monkeypatch.setattr(main, "prepare_job_retry", lambda _: {"status": "SUCCESS", "attempt_no": None})

    response = client.post("/api/v1/jobs/job-1/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_RETRYABLE"


def test_create_job_reports_idempotency_conflict(monkeypatch, tmp_path):
    stored_file = tmp_path / "stored.csv"
    stored_file.write_text("external_id,name,amount,record_date\nA-1,Alice,1,2026-01-01\n")
    monkeypatch.setattr(main, "save_upload", lambda _: ("input.csv", str(stored_file), "b" * 64))
    monkeypatch.setattr(main, "insert_job", lambda *_args: (_ for _ in ()).throw(IdempotencyConflictError("same-key")))

    response = client.post(
        "/api/v1/jobs",
        files={"file": ("input.csv", b"external_id,name,amount,record_date\nA-1,Alice,1,2026-01-01\n")},
        headers={"Idempotency-Key": "same-key"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
