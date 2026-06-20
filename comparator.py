from dataclasses import dataclass, field
from rapidfuzz import fuzz
from normalizer import normalize_amount, normalize_date, normalize_text
from config import (
    FUZZY_FIELDS, EXACT_FIELDS, AMOUNT_FIELDS, DATE_FIELDS,
    FUZZY_THRESHOLDS, INVALID_DOC_MIN_FIELDS, FIELDS,
)


@dataclass
class ComparisonResult:
    status: str
    comments: list[str] = field(default_factory=list)
    extracted: dict = field(default_factory=dict)


def _field_label(field_key: str) -> str:
    return field_key.replace("_", " ").title()


def _is_valid_document(extracted: dict) -> bool:
    found = sum(1 for v in extracted.values() if v is not None and str(v).strip())
    return found >= INVALID_DOC_MIN_FIELDS


def _is_digit_scale_error(extracted_val, expected_val) -> bool:
    """True when two amounts differ only by a 10x/100x/1000x factor — a dropped
    or added zero, not a genuinely different number. Routes to human review
    instead of a hard rejection."""
    e = normalize_amount(str(extracted_val))
    x = normalize_amount(str(expected_val))
    if not e or not x:
        return False
    hi, lo = (e, x) if e > x else (x, e)
    ratio = hi / lo
    for factor in (10, 100, 1000):
        if abs(ratio - factor) < 0.01:
            return True
    return False


def _fields_match(field_key: str, extracted_val, expected_val) -> bool:
    if extracted_val is None or str(extracted_val).strip() == "":
        return False

    if field_key in AMOUNT_FIELDS:
        e = normalize_amount(str(extracted_val))
        x = normalize_amount(str(expected_val))
        if e is None or x is None:
            return False
        return e == x

    if field_key in DATE_FIELDS:
        e = normalize_date(str(extracted_val))
        x = normalize_date(str(expected_val))
        if e is None or x is None:
            return False
        return e == x

    if field_key in EXACT_FIELDS:
        e = str(extracted_val).strip()
        x = str(expected_val).strip()
        # accept if extracted ends with expected — handles "AHFLN No. 337887565" vs "337887565"
        return e == x or e.endswith(x)

    if field_key in FUZZY_FIELDS:
        threshold = FUZZY_THRESHOLDS.get(field_key, 80)
        score = fuzz.ratio(
            normalize_text(str(extracted_val)),
            normalize_text(str(expected_val)),
        )
        return score >= threshold

    score = fuzz.ratio(
        normalize_text(str(extracted_val)),
        normalize_text(str(expected_val)),
    )
    return score >= 80


def compare_fields(extracted: dict, expected: dict, needs_review: bool = False) -> ComparisonResult:
    if needs_review:
        return ComparisonResult(
            status="NEEDS_REVIEW",
            comments=["Document could not be read clearly. Please re-upload a higher-quality "
                      "scan or verify this application manually."],
            extracted=extracted,
        )

    if not _is_valid_document(extracted):
        return ComparisonResult(
            status="CHANGES_REQUESTED",
            comments=["Invalid document uploaded. Please upload a valid sanctioned letter, "
                      "disbursement letter, or banker confirmation."],
            extracted=extracted,
        )

    comments = []        # genuine mismatches → CHANGES_REQUESTED
    review_comments = [] # digit-scale amount errors → NEEDS_REVIEW
    for f in FIELDS:
        extracted_val = extracted.get(f)
        expected_val = expected.get(f)

        if not expected_val:
            continue

        if _fields_match(f, extracted_val, expected_val):
            continue

        label = _field_label(f)
        if f in AMOUNT_FIELDS and _is_digit_scale_error(extracted_val, expected_val):
            review_comments.append(
                f"{label} digit error: document shows '{extracted_val}', "
                f"expected '{expected_val}' (differs by a factor of 10 — likely a "
                f"mis-read zero). Please verify manually."
            )
        else:
            comments.append(
                f"{label} mismatch: document shows '{extracted_val}', "
                f"expected '{expected_val}'"
            )

    # Genuine mismatch always wins — a real problem surfaces as CHANGES_REQUESTED.
    if comments:
        return ComparisonResult(status="CHANGES_REQUESTED", comments=comments, extracted=extracted)
    # Only ambiguous digit-scale amount errors remain → route to human.
    if review_comments:
        return ComparisonResult(status="NEEDS_REVIEW", comments=review_comments, extracted=extracted)
    return ComparisonResult(status="APPROVED", comments=[], extracted=extracted)
