from fastapi.testclient import TestClient
from datetime import datetime

import app.main as main
from app.main import app
from worker.worker import parse_queue_message


client = TestClient(app)


def test_cancel_endpoint_moves_running_job_to_canceling(monkeypatch):
    job = {
        "id": "job-1",
        "name": "demo",
        "status": "CANCELING",
        "source_file_name": "demo.csv",
        "total_records": 0,
        "success_records": 0,
        "failed_records": 0,
        "retry_count": 0,
        "last_error_code": "CANCEL_REQUESTED",
        "last_error_message": "已请求取消，等待 Worker 安全停止",
        "created_at": datetime(2026, 1, 1),
        "started_at": None,
        "finished_at": None,
    }
    monkeypatch.setattr(main, "get_job", lambda _: job)
    monkeypatch.setattr(main, "request_job_cancel", lambda _: "RUNNING")

    response = client.post("/api/v1/jobs/job-1/cancel")

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "CANCELING"
    assert response.json()["meta"]["previous_status"] == "RUNNING"


def test_cancel_endpoint_rejects_terminal_job(monkeypatch):
    monkeypatch.setattr(main, "get_job", lambda _: {"id": "job-1", "status": "SUCCESS"})
    monkeypatch.setattr(main, "request_job_cancel", lambda _: "SUCCESS")

    response = client.post("/api/v1/jobs/job-1/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_worker_accepts_json_and_legacy_queue_messages():
    assert parse_queue_message('{"job_id":"job-1","attempt_no":2}') == ("job-1", 2)
    assert parse_queue_message("job-2") == ("job-2", 0)
