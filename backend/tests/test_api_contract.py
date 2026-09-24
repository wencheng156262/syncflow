from fastapi.testclient import TestClient

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
