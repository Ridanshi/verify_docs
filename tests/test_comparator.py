import pytest
from comparator import compare_fields, ComparisonResult


def _base_extracted():
    return {
        "customer_name": "Zainab Medicals",
        "bank_name": "Mahindra Finance",
        "loan_account_number": "LAPSEC000007708",
        "application_id": "91950",
        "sanction_amount": "63,50,000",
        "disbursement_amount": "63,50,000",
        "loan_type": "LAP Non Individual",
        "branch": "T.nagar",
        "disbursement_date": "31 Jan 2026",
    }

def _base_expected():
    return {
        "customer_name": "ZAINAB MEDICALS",
        "bank_name": "Mahindra Finance",
        "loan_account_number": "LAPSEC000007708",
        "application_id": "91950",
        "sanction_amount": "6350000",
        "disbursement_amount": "6350000",
        "loan_type": "LAP Non Individual",
        "branch": "T.nagar",
        "disbursement_date": "2026-01-31",
    }


def test_all_match_returns_approved():
    result = compare_fields(_base_extracted(), _base_expected())
    assert result.status == "APPROVED"
    assert result.comments == []


def test_amount_mismatch_returns_changes_requested():
    extracted = _base_extracted()
    extracted["sanction_amount"] = "Rs.50.00 lakhs"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"
    assert any("Sanction Amount" in c for c in result.comments)


def test_id_mismatch_returns_changes_requested():
    extracted = _base_extracted()
    extracted["loan_account_number"] = "LAPSEC000007709"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"
    assert any("Loan Account Number" in c for c in result.comments)


def test_name_casing_difference_approved():
    result = compare_fields(_base_extracted(), _base_expected())
    assert result.status == "APPROVED"


def test_null_extracted_field_is_mismatch():
    extracted = _base_extracted()
    extracted["branch"] = None
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"
    assert any("Branch" in c for c in result.comments)


def test_comment_contains_both_values():
    extracted = _base_extracted()
    extracted["sanction_amount"] = "Rs.50.00 lakhs"
    result = compare_fields(extracted, _base_expected())
    assert any("Rs.50.00 lakhs" in c or "5000000" in c for c in result.comments)


def test_amount_digit_drop_routes_to_needs_review():
    # 6350000 vs 635000 = 10x factor → dropped zero, not a real mismatch
    extracted = _base_extracted()
    extracted["sanction_amount"] = "635000"
    extracted["disbursement_amount"] = "635000"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "NEEDS_REVIEW"
    assert any("digit error" in c for c in result.comments)


def test_genuine_mismatch_overrides_digit_error():
    # name genuinely wrong + amount digit drop → CHANGES_REQUESTED wins
    extracted = _base_extracted()
    extracted["customer_name"] = "Totally Different Person"
    extracted["sanction_amount"] = "635000"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"


def test_genuine_amount_mismatch_not_treated_as_digit_error():
    # 6350000 vs 7100000 = ~1.12x, not a 10x factor → real CHANGES_REQUESTED
    extracted = _base_extracted()
    extracted["sanction_amount"] = "7100000"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"


def test_invalid_document_too_few_fields():
    extracted = {k: None for k in _base_extracted()}
    extracted["customer_name"] = "Someone"
    extracted["bank_name"] = "SomeBank"
    result = compare_fields(extracted, _base_expected())
    assert result.status == "CHANGES_REQUESTED"
    assert any("Invalid document" in c for c in result.comments)
