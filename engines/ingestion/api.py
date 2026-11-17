from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException

from .config import settings
from .pipeline import run_ingestion
from .database import record_ingestion_result

app = FastAPI(title="PrepFreeX Ingestion API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "prepfreex-ingestion-engine"}


@app.post("/api/ingestion/upload")
def upload_pdf(
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    persist: bool = Form(True),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")
    allowed_types = {"auto", "full_test", "chapter_test", "question_bank"}
    if document_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"document_type must be one of {sorted(allowed_types)}")
    upload_dir = settings.input_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    target = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    max_bytes = 100 * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="PDF exceeds the 100 MB local upload limit")
                out.write(chunk)
        report = run_ingestion(target)
        report["document_type_requested"] = document_type
        if persist:
            job_id = record_ingestion_result(report, target)
            report["database_job_id"] = job_id
        return report
    except HTTPException:
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
