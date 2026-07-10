# api.py — FastAPI wrapper around the existing verify_docs pipeline.
#
# No database code here. This endpoint receives the "expected" values as a
# JSON string (built by the caller — e.g. the Loan Networks backend, which
# already has the case's real values) plus a document, and returns a verdict.
# The comparison logic itself lives entirely in comparator.py, unchanged.

import json
import os
import tempfile

from fastapi import FastAPI, File, Form, UploadFile

from preprocessor import load_image
from extractor import extract_fields
from comparator import compare_fields

app = FastAPI()


@app.post("/verify")
async def verify(expected: str = Form(...), document: UploadFile = File(...)):
    expected_dict = json.loads(expected)

    suffix = os.path.splitext(document.filename or "")[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await document.read())
        tmp_path = tmp.name

    try:
        image = load_image(tmp_path)
        extracted = extract_fields(image)
        result = compare_fields(extracted, expected_dict)
    finally:
        os.unlink(tmp_path)

    return {
        "verdict": result.status,
        "comments": result.comments,
        "extracted": result.extracted,
    }
