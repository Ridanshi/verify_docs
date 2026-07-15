import io
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import app
from comparator import ComparisonResult

client = TestClient(app)

VALID_EXPECTED = {
    "customer_name": "Jane Doe",
    "bank_name": "HDFC",
    "application_id": "APP123",
    "sanction_amount": 500000,
    "disbursement_amount": 500000,
    "loan_type": "Home Loan",
    "branch": "Andheri",
    "disbursement_date": "2026-01-31",
    "loan_account_number": "HL1234567890",
}


@patch("api.compare_fields")
@patch("api.extract_fields")
@patch("api.load_image")
def test_verify_returns_approved_verdict(mock_load_image, mock_extract_fields, mock_compare_fields):
    mock_load_image.return_value = "fake-image-object"
    mock_extract_fields.return_value = {"customer_name": "Jane Doe"}
    mock_compare_fields.return_value = ComparisonResult(
        status="APPROVED", comments=[], extracted={"customer_name": "Jane Doe"}
    )

    response = client.post(
        "/verify",
        data={"expected": json.dumps(VALID_EXPECTED)},
        files={"document": ("doc.pdf", io.BytesIO(b"%PDF-1.4 dummy"), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "verdict": "APPROVED",
        "comments": [],
        "extracted": {"customer_name": "Jane Doe"},
    }
    mock_load_image.assert_called_once()
    mock_extract_fields.assert_called_once_with("fake-image-object")
    mock_compare_fields.assert_called_once_with({"customer_name": "Jane Doe"}, VALID_EXPECTED)


def test_verify_requires_document_file():
    response = client.post("/verify", data={"expected": json.dumps(VALID_EXPECTED)})

    assert response.status_code == 422  # FastAPI's own validation — no file provided


@patch("api.compare_fields")
@patch("api.refine_amount_fields")
@patch("api.extract_fields")
@patch("api.load_image_high_res")
@patch("api.load_image")
def test_verify_runs_amount_refinement_when_enough_fields_found(
    mock_load_image, mock_load_image_high_res, mock_extract_fields, mock_refine_amount_fields, mock_compare_fields
):
    # 3+ non-null fields → looks like a real document → refinement pass should run
    main_pass_result = {"customer_name": "Jane Doe", "bank_name": "HDFC", "sanction_amount": "5,00,000"}
    refined_result = {**main_pass_result, "sanction_amount": "50,00,000"}

    mock_load_image.return_value = "fake-image-object"
    mock_load_image_high_res.return_value = "fake-high-res-image-object"
    mock_extract_fields.return_value = main_pass_result
    mock_refine_amount_fields.return_value = refined_result
    mock_compare_fields.return_value = ComparisonResult(status="APPROVED", comments=[], extracted=refined_result)

    response = client.post(
        "/verify",
        data={"expected": json.dumps(VALID_EXPECTED)},
        files={"document": ("doc.pdf", io.BytesIO(b"%PDF-1.4 dummy"), "application/pdf")},
    )

    assert response.status_code == 200
    mock_load_image_high_res.assert_called_once()
    mock_refine_amount_fields.assert_called_once_with("fake-high-res-image-object", main_pass_result)
    mock_compare_fields.assert_called_once_with(refined_result, VALID_EXPECTED)


@patch("api.compare_fields")
@patch("api.refine_amount_fields")
@patch("api.extract_fields")
@patch("api.load_image_high_res")
@patch("api.load_image")
def test_verify_skips_refinement_for_near_empty_extraction(
    mock_load_image, mock_load_image_high_res, mock_extract_fields, mock_refine_amount_fields, mock_compare_fields
):
    # Only 1 non-null field → looks invalid/unreadable → skip the extra GPU pass
    sparse_result = {"customer_name": "Jane Doe"}

    mock_load_image.return_value = "fake-image-object"
    mock_extract_fields.return_value = sparse_result
    mock_compare_fields.return_value = ComparisonResult(status="CHANGES_REQUESTED", comments=[], extracted=sparse_result)

    response = client.post(
        "/verify",
        data={"expected": json.dumps(VALID_EXPECTED)},
        files={"document": ("doc.pdf", io.BytesIO(b"%PDF-1.4 dummy"), "application/pdf")},
    )

    assert response.status_code == 200
    mock_load_image_high_res.assert_not_called()
    mock_refine_amount_fields.assert_not_called()
    mock_compare_fields.assert_called_once_with(sparse_result, VALID_EXPECTED)
