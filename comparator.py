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

    comments = []
    for f in FIELDS:
        extracted_val = extracted.get(f)
        expected_val = expected.get(f)

        if not expected_val:
            continue

        if not _fields_match(f, extracted_val, expected_val):
            label = _field_label(f)
            comments.append(
                f"{label} mismatch: document shows '{extracted_val}', "
                f"expected '{expected_val}'"
            )

    status = "APPROVED" if not comments else "CHANGES_REQUESTED"
    return ComparisonResult(status=status, comments=comments, extracted=extracted)
