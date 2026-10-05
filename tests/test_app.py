from io import BytesIO
from pathlib import Path
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

import app as application

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "pdfs" / "development" / "Table 02_Ver.01.pdf"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "STORE", tmp_path / "uploads")
    application.JOBS.clear()
    with TestClient(application.app) as client:
        yield client
    application.JOBS.clear()


def await_job(client, job_id):
    for _ in range(200):
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("complete", "failed"):
            return job
        time.sleep(.025)
    pytest.fail("Background extraction did not finish")


def test_upload_review_download_and_clear(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["ocr_enabled"] is False
    response = client.post("/api/jobs", files=[("files", (SAMPLE.name, SAMPLE.read_bytes(), "application/pdf"))])
    assert response.status_code == 202
    job_id = response.json()["id"]
    job = await_job(client, job_id)
    assert job["documents"][0]["field_count"] == 31
    base = f"/api/jobs/{job_id}/documents/0"
    result = client.get(base).json()
    assert result["document"]["filename"] == SAMPLE.name
    json_download = client.get(base + "/download")
    assert json_download.json() == result
    assert "attachment" in json_download.headers["content-disposition"]
    image = client.get(base + "/pages/1")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get(base + "/pages/2").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/documents/unknown").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(base).status_code == 404
    assert list(application.STORE.iterdir()) == []


def test_batch_duplicates_and_partial_failure(client):
    data = SAMPLE.read_bytes()
    response = client.post("/api/jobs", files=[
        ("files", ("same.pdf", data)), ("files", ("same.pdf", data)),
        ("files", ("broken.pdf", b"%PDF-invalid"))])
    job = await_job(client, response.json()["id"])
    assert [d["status"] for d in job["documents"]] == ["complete", "complete", "failed"]
    zip_response = client.get(f"/api/jobs/{job['id']}/download")
    with ZipFile(BytesIO(zip_response.content)) as archive:
        assert set(archive.namelist()) == {"01_same.json", "02_same.json", "errors.json"}
    assert client.get(f"/api/jobs/{job['id']}/documents/2").status_code == 409


def test_table11_upload_and_download_keep_year_and_month_context(client):
    source = ROOT / "pdfs/development/Table 11_Ver.01.pdf"
    response = client.post("/api/jobs", files=[("files", (source.name, source.read_bytes(), "application/pdf"))])
    assert response.status_code == 202
    job = await_job(client, response.json()["id"])
    assert job["documents"][0]["status"] == "complete"
    base = f"/api/jobs/{job['id']}/documents/0"
    result = client.get(base).json()
    assert result["parser_version"] == "1.3.0"
    values = {(v["row_label"], v["column_label"]): v["text"]
              for f in result["fields"] for v in f["values"] if v["column_label"]}
    assert len(values) == 390
    assert values[("CODE", "2026")] == "T"
    assert values[("JAN", "2026")] == "S"
    assert values[("JAN", "2041")] == "A"
    assert values[("DEC", "2055")] == "T"
    assert client.get(base + "/download").json() == result


def test_reject_invalid_uploads_without_leaving_files(client, monkeypatch):
    assert client.post("/api/jobs", files=[("files", ("image.txt", b"abc"))]).status_code == 400
    assert client.post("/api/jobs", files=[("files", ("pretend.pdf", b"not a pdf"))]).status_code == 400
    assert client.post("/api/jobs", files=[("files", ("empty.pdf", b""))]).status_code == 400
    assert client.post("/api/jobs", files=[("files", ("test.pdf", b"%PDF-"))] * 11).status_code == 400
    monkeypatch.setattr(application, "MAX_FILE_BYTES", 10)
    assert client.post("/api/jobs", files=[("files", ("test.pdf", b"%PDF-" + b"x" * 10))]).status_code == 413
    assert not application.JOBS
    assert list(application.STORE.iterdir()) == []


def test_old_jobs_expire(client, monkeypatch):
    response = client.post("/api/jobs", files=[("files", (SAMPLE.name, SAMPLE.read_bytes()))])
    job_id = response.json()["id"]
    await_job(client, job_id)
    application.JOBS[job_id]["last_access"] = time.time() - application.RETENTION_SECONDS - 5
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert list(application.STORE.iterdir()) == []
