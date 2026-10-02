from fastapi.testclient import TestClient

import app.main as main
from app.main import app


client = TestClient(app)


def test_create_job_rejects_non_csv_without_database_access():
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("notes.txt", b"not csv")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_EXTENSION"


def test_list_jobs_rejects_unknown_status_without_database_access():
    response = client.get("/api/v1/jobs?status=UNKNOWN")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_job_detail_returns_unified_not_found_error(monkeypatch):
    monkeypatch.setattr(main, "get_job", lambda _: None)

    response = client.get("/api/v1/jobs/missing-job")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "JOB_NOT_FOUND",
            "message": "任务不存在",
            "details": [],
        }
    }


def test_openapi_exposes_week2_job_endpoints():
    paths = app.openapi()["paths"]

    assert "/api/v1/jobs" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert {"get", "post"}.issubset(paths["/api/v1/jobs"])
    assert "get" in paths["/api/v1/jobs/{job_id}"]


def test_job_errors_returns_paginated_error_details(monkeypatch):
    monkeypatch.setattr(main, "get_job", lambda _: {"id": "job-1"})
    monkeypatch.setattr(
        main,
        "list_job_errors",
        lambda *_args, **_kwargs: (
            [
                {
                    "job_id": "job-1",
                    "row_number": 3,
                    "field_name": "amount",
                    "error_code": "AMOUNT_INVALID",
                    "error_message": "amount 必须是非负数字且最多两位小数",
                    "raw_row": '{"amount":"1.234"}',
                    "created_at": __import__("datetime").datetime(2026, 1, 1),
                }
            ],
            1,
        ),
    )

    response = client.get("/api/v1/jobs/job-1/errors?page=1&page_size=20")

    assert response.status_code == 200
    assert response.json()["data"][0]["field_name"] == "amount"
    assert response.json()["data"][0]["raw_row"] == {"amount": "1.234"}
    assert response.json()["meta"]["total"] == 1


def test_openapi_exposes_week3_error_endpoint():
    assert "/api/v1/jobs/{job_id}/errors" in app.openapi()["paths"]


def test_openapi_exposes_week4_cancel_endpoint():
    assert "/api/v1/jobs/{job_id}/cancel" in app.openapi()["paths"]
