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
