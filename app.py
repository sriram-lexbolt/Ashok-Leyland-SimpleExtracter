"""Local PDF upload application. Run with: python -m uvicorn app:app."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from io import BytesIO
import json
import logging
from pathlib import Path
import shutil
import threading
import time
from urllib.parse import quote
import uuid
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import pypdfium2 as pdfium

from extractor.engine import ExtractionError, extract_pdf

BASE = Path(__file__).resolve().parent
STORE = BASE / "tmp" / "uploads"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_FILES = 10
MAX_JOBS = 12
RETENTION_SECONDS = 60 * 60
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
RENDER_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def _remove_job_dir(path: Path) -> None:
    # Only remove application-owned job directories within the upload store.
    resolved = path.resolve()
    if resolved.parent == STORE.resolve() and len(resolved.name) == 32:
        shutil.rmtree(resolved, ignore_errors=True)


def _cleanup() -> None:
    with LOCK:
        now = time.time()
        for job_id, job in list(JOBS.items()):
            if job["status"] in ("complete", "failed") and now - job["last_access"] > RETENTION_SECONDS:
                _remove_job_dir(job["folder"])
                del JOBS[job_id]


@asynccontextmanager
async def lifespan(application: FastAPI):
    STORE.mkdir(parents=True, exist_ok=True)
    # Previous-process jobs have no live handles and can be safely cleared.
    for path in STORE.iterdir():
        if path.is_dir() and len(path.name) == 32 and all(c in "0123456789abcdef" for c in path.name):
            _remove_job_dir(path)
    application.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-extract")
    yield
    application.state.executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="Jags AL Data Extracter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "max_files": MAX_FILES, "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
            "max_batch_mb": MAX_BATCH_BYTES // (1024 * 1024), "max_pages": 200,
            "ocr_enabled": False, "retention_minutes": RETENTION_SECONDS // 60}


def _job(job_id: str) -> dict:
    _cleanup()
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "This extraction has expired or does not exist. Upload the PDF again.")
        job["last_access"] = time.time()
        return job


def _document(job_id: str, doc_id: str) -> dict:
    job = _job(job_id)
    doc = next((d for d in job["documents"] if d["id"] == doc_id), None)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


def _public(job: dict) -> dict:
    with LOCK:
        return {"id": job["id"], "status": job["status"], "documents": [
            {key: value for key, value in d.items() if key not in ("path", "result")}
            for d in job["documents"]]}


def _run_job(job_id: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        job["status"] = "processing"
    for doc in job["documents"]:
        with LOCK:
            doc["status"] = "processing"
        def progress(done: int, total: int) -> None:
            with LOCK:
                doc.update(pages_done=done, page_count=total)
        try:
            result = extract_pdf(doc["path"], doc["filename"], progress)
            with LOCK:
                doc.update(status="complete", result=result, field_count=len(result["fields"]),
                           table_count=result["extraction"]["table_count"],
                           warning_count=len(result["extraction"]["warnings"]))
        except ExtractionError as exc:
            with LOCK:
                doc.update(status="failed", error=str(exc))
        except Exception:
            logger.exception("Extraction failed for document %s", doc["id"])
            with LOCK:
                doc.update(status="failed", error="Extraction failed for this PDF. Check whether it is damaged or password protected.")
    with LOCK:
        job["status"] = "complete" if any(d["status"] == "complete" for d in job["documents"]) else "failed"
        job["last_access"] = time.time()


@app.post("/api/jobs", status_code=202)
async def upload(files: list[UploadFile] = File(...)):
    _cleanup()
    if not 1 <= len(files) <= MAX_FILES:
        for file in files:
            await file.close()
        raise HTTPException(400, f"Upload 1 to {MAX_FILES} PDFs at a time.")
    job_id = uuid.uuid4().hex
    folder = STORE / job_id
    with LOCK:
        if len(JOBS) >= MAX_JOBS:
            for file in files:
                await file.close()
            raise HTTPException(429, "The local queue is full. Clear a finished batch or try again later.")
        folder.mkdir(parents=True)
        job = {"id": job_id, "status": "uploading", "folder": folder, "documents": [], "last_access": time.time()}
        JOBS[job_id] = job
    try:
        total_bytes = 0
        for index, file in enumerate(files):
            filename = Path((file.filename or "document.pdf").replace("\\", "/")).name
            if not filename.lower().endswith(".pdf") or len(filename) > 200 or any(ord(c) < 32 for c in filename):
                raise HTTPException(400, "Choose a file with a .pdf extension and a valid filename.")
            path = folder / f"{index}.pdf"
            size = 0
            with path.open("wb") as stream:
                while chunk := await file.read(64 * 1024):
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(413, f"{filename} exceeds the 25 MB limit.")
                    if total_bytes > MAX_BATCH_BYTES:
                        raise HTTPException(413, "The batch exceeds the 100 MB limit.")
                    stream.write(chunk)
            with path.open("rb") as stream:
                if b"%PDF-" not in stream.read(1024):
                    raise HTTPException(400, f"{filename} is not a valid PDF.")
            with LOCK:
                job["documents"].append({"id": str(index), "filename": filename, "size_bytes": size,
                                         "path": path, "status": "queued", "pages_done": 0, "page_count": None,
                                         "field_count": 0, "table_count": 0, "warning_count": 0, "error": None})
        with LOCK:
            job["status"] = "queued"
        app.state.executor.submit(_run_job, job_id)
        return _public(job)
    except BaseException:
        with LOCK:
            JOBS.pop(job_id, None)
        _remove_job_dir(folder)
        raise
    finally:
        for file in files:
            await file.close()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _public(_job(job_id))


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    with LOCK:
        job = _job(job_id)
        if job["status"] not in ("complete", "failed"):
            raise HTTPException(409, "Wait for this batch to finish before clearing it.")
        JOBS.pop(job_id)
        _remove_job_dir(job["folder"])
    return Response(status_code=204)


def _result(job_id: str, doc_id: str) -> dict:
    doc = _document(job_id, doc_id)
    if doc["status"] != "complete":
        raise HTTPException(409, doc.get("error") or "This document is still processing.")
    return doc["result"]


def _download_headers(filename: str) -> dict:
    return {"Content-Disposition": f"attachment; filename=extracted.json; filename*=UTF-8''{quote(filename)}"}


@app.get("/api/jobs/{job_id}/documents/{doc_id}")
def document_result(job_id: str, doc_id: str):
    return _result(job_id, doc_id)


@app.get("/api/jobs/{job_id}/documents/{doc_id}/download")
def download_json(job_id: str, doc_id: str):
    result = _result(job_id, doc_id)
    filename = Path(result["document"]["filename"]).stem + ".json"
    return Response(json.dumps(result, indent=2, ensure_ascii=False), media_type="application/json",
                    headers=_download_headers(filename))


@app.get("/api/jobs/{job_id}/download")
def download_zip(job_id: str):
    job = _job(job_id)
    if job["status"] not in ("complete", "failed"):
        raise HTTPException(409, "Wait for the batch to finish before downloading it.")
    successful = [d for d in job["documents"] if d["status"] == "complete"]
    if not successful:
        raise HTTPException(409, "There are no extracted documents to download.")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for d in successful:
            name = f"{int(d['id']) + 1:02d}_{Path(d['filename']).stem}.json"
            archive.writestr(name, json.dumps(d["result"], indent=2, ensure_ascii=False))
        failed = [{"filename": d["filename"], "error": d["error"]} for d in job["documents"] if d["status"] == "failed"]
        if failed:
            archive.writestr("errors.json", json.dumps(failed, indent=2, ensure_ascii=False))
    return Response(output.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="extracted_documents.zip"'})


@app.get("/api/jobs/{job_id}/documents/{doc_id}/pages/{page_number}")
def page_image(job_id: str, doc_id: str, page_number: int):
    doc = _document(job_id, doc_id)
    result = _result(job_id, doc_id)
    if not 1 <= page_number <= result["document"]["page_count"]:
        raise HTTPException(404, "Page not found.")
    image_path = doc["path"].parent / f"{doc_id}-page{page_number}.png"
    with RENDER_LOCK:
        if not image_path.exists():
            with pdfium.PdfDocument(str(doc["path"])) as pdf:
                page = pdf[page_number - 1]
                bitmap = page.render(scale=min(1600 / page.get_width(), 2.5))
                image = bitmap.to_pil()
                image.save(image_path)
                image.close()
                bitmap.close()
                page.close()
    return FileResponse(image_path, media_type="image/png")
