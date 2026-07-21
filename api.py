# api.py — FastAPI wrapper around the existing verify_docs pipeline.
#
# Async job model: /verify enqueues work and returns a job_id immediately;
# the caller polls /result/{job_id}. This exists because free-tier HTTP
# tunnels (ngrok, Cloudflare Tunnel) cap a single request at ~60-100s,
# but VLM inference on this pipeline routinely takes 2-14 minutes. Every
# request in this model finishes in under a second — no tunnel timeout
# can hit us regardless of how long the underlying pipeline takes.
#
# No database here — expected values are passed in by the caller
# (the Loan Networks backend, which already has them). Comparison logic
# still lives entirely in comparator.py, unchanged.

import json
import os
import tempfile
import threading
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from preprocessor import load_image, load_image_high_res
from extractor import extract_fields, refine_amount_fields
from comparator import compare_fields
from config import INVALID_DOC_MIN_FIELDS

app = FastAPI()

# Kaggle runs a single-worker uvicorn — no cross-process coordination needed,
# a plain dict + lock is enough. Jobs stay in memory only; if the notebook
# restarts, callers will see 404 on their old job_id and re-submit.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _run_pipeline(job_id: str, expected_dict: dict, tmp_path: str) -> None:
    """Executed on a worker thread — same pipeline as the old synchronous
    /verify endpoint. Writes the outcome into _JOBS[job_id] when done."""
    try:
        image = load_image(tmp_path)
        extracted = extract_fields(image)

        fields_found = sum(1 for v in extracted.values() if v is not None)
        if fields_found >= INVALID_DOC_MIN_FIELDS:
            image_high_res = load_image_high_res(tmp_path)
            extracted = refine_amount_fields(image_high_res, extracted)

        result = compare_fields(extracted, expected_dict)
        payload = {
            "verdict": result.status,
            "comments": result.comments,
            "extracted": result.extracted,
        }
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status": "done", "result": payload}
    except Exception as exc:
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status": "error", "error": str(exc)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.post("/verify")
async def verify(expected: str = Form(...), document: UploadFile = File(...)):
    """Enqueue a verification job. Returns a job_id immediately.
    Poll /result/{job_id} for status/verdict."""
    expected_dict = json.loads(expected)

    # Persist the upload to disk BEFORE returning, so the worker thread has
    # something to read after the request ends and UploadFile is closed.
    suffix = os.path.splitext(document.filename or "")[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await document.read())
        tmp_path = tmp.name

    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "running"}

    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, expected_dict, tmp_path),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "running"}


@app.get("/result/{job_id}")
async def result(job_id: str):
    """Poll for a job's outcome.
    - 200 + status="running"           → still working, poll again later
    - 200 + status="done"    + result  → verdict is in `result`
    - 200 + status="error"   + error   → pipeline failed, message in `error`
    - 404                              → job_id unknown (never submitted, or notebook restarted)"""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")

    return {"job_id": job_id, **job}
