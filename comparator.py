from dataclasses import dataclass, field # Importing this helps us escape writing boilerplate constructors
from rapidfuzz import fuzz # Fast fuzzy string matching library used for names, banks, branches, etc.
from normalizer import normalize_amount, normalize_date, normalize_text, words_to_number
from config import (
    FUZZY_FIELDS, EXACT_FIELDS, AMOUNT_FIELDS, DATE_FIELDS,
    FUZZY_THRESHOLDS, INVALID_DOC_MIN_FIELDS, FIELDS, AMOUNT_WORD_FIELDS,
)

# Standard result object returned by compare_fields(). Contains final status, reviewer comments, and extracted values.
@dataclass
class ComparisonResult:
    status: str
    comments: list[str] = field(default_factory=list)
    extracted: dict = field(default_factory=dict)

# Convert internal field names into human-readable labels for comments. (sanction_amount -> Sanction Amount)
def _field_label(field_key: str) -> str:
    return field_key.replace("_", " ").title()


# Documents with too few extracted fields are considered invalid uploads. 
# Prevents approving blank pages, unrelated documents, or failed OCR outputs.
def _is_valid_document(extracted: dict) -> bool:
    # Missing extracted values can never match.
    found = sum(1 for v in extracted.values() if v is not None and str(v).strip())
    return found >= INVALID_DOC_MIN_FIELDS


def _amounts_close(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) < 0.01


def _scale_factor(a, b) -> bool:
    """True when two amounts differ only by a 10x/100x/1000x factor — a dropped
    or added zero, not a genuinely different number."""
    if not a or not b:
        return False
    hi, lo = (a, b) if a > b else (b, a)
    ratio = hi / lo
    return any(abs(ratio - f) < 0.01 for f in (10, 100, 1000))


def _reconcile_amount(digit_str, word_str) -> tuple[float | None, bool]:
    """Cross-check the amount's digits against its words.
    Returns (best_value, internal_conflict).

    - words missing        -> trust digits
    - digits missing       -> trust words
    - agree                -> trust either
    - differ by 10x/100x   -> digits dropped a zero; WORDS win (authoritative)
    - differ otherwise     -> unresolvable internal conflict -> (None, True)
    """
    d = normalize_amount(str(digit_str)) if digit_str else None
    w = words_to_number(str(word_str)) if word_str else None
    if d is None and w is None:
        return None, False
    if w is None:
        return d, False
    if d is None:
        return w, False
    if _amounts_close(d, w):
        return d, False
    if _scale_factor(d, w):
        return w, False          # words recover the dropped/added zero
    return None, True            # digits and words genuinely disagree


def _fields_match(field_key: str, extracted_val, expected_val) -> bool:
    # Missing extracted values can never match
    if extracted_val is None or str(extracted_val).strip() == "":
        return False

    if field_key in AMOUNT_FIELDS: # Amount fields are normalized into floats before comparison.
        e = normalize_amount(str(extracted_val))
        x = normalize_amount(str(expected_val))
        if e is None or x is None:
            return False
        return e == x

    if field_key in DATE_FIELDS: # Date fields are converted to YYYY-MM-DD before comparison.
        e = normalize_date(str(extracted_val))
        x = normalize_date(str(expected_val))
        if e is None or x is None:
            return False
        return e == x
     
    # IDs require exact matching because even one wrong character usually identifies a different application/account.
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


def _compare_amount(f: str, extracted: dict, expected_val) -> tuple[str, str]:
    """Compare one amount field using digit/word reconciliation.
    Returns (outcome, comment) where outcome is 'match' | 'mismatch' | 'review'.
    """
    label = _field_label(f)
    digit_str = extracted.get(f)
    word_str = extracted.get(AMOUNT_WORD_FIELDS[f])
    exp_num = normalize_amount(str(expected_val))

    value, conflict = _reconcile_amount(digit_str, word_str)

    # The document's own digits and words disagree — can't trust either.
    if conflict:
        return "review", (
            f"{label} unclear: digits '{digit_str}' and words '{word_str}' disagree "
            f"on the document. Please verify manually."
        )

    if _amounts_close(value, exp_num):
        return "match", ""

    # Reconciled value disagrees with the expected value.
    # If there were no words to confirm and the digits are off by exactly a
    # 10x/100x factor, it is likely a mis-read zero — defer to a human rather
    # than hard-reject.
    word_num = words_to_number(str(word_str)) if word_str else None
    digit_num = normalize_amount(str(digit_str)) if digit_str else None
    if word_num is None and _scale_factor(digit_num, exp_num):
        return "review", (
            f"{label} digit error: document shows '{digit_str}', expected "
            f"'{expected_val}' (off by a factor of 10 — likely a mis-read zero, "
            f"no amount-in-words to confirm). Please verify manually."
        )

    return "mismatch", (
        f"{label} mismatch: document shows '{digit_str}', expected '{expected_val}'"
    )


def compare_fields(extracted: dict, expected: dict) -> ComparisonResult:
    if not _is_valid_document(extracted): # Reject documents that do not contain enough usable information.
        return ComparisonResult(
            status="CHANGES_REQUESTED",
            comments=["Invalid document uploaded. Please upload a valid sanctioned letter, "
                      "disbursement letter, or banker confirmation."],
            extracted=extracted,
        )

    comments = []        # genuine mismatches → CHANGES_REQUESTED
    review_comments = [] # unresolved amount uncertainty → NEEDS_REVIEW
    for f in FIELDS: # Compare every configured field
        expected_val = expected.get(f)
        if not expected_val: # Ignore fields that have no expected value.
            continue

        if f in AMOUNT_FIELDS:
            outcome, comment = _compare_amount(f, extracted, expected_val)
            if outcome == "match":
                continue
            (review_comments if outcome == "review" else comments).append(comment)
            continue

        if _fields_match(f, extracted.get(f), expected_val): # Field matches successfully
            continue
        comments.append(
            f"{_field_label(f)} mismatch: document shows '{extracted.get(f)}', "
            f"expected '{expected_val}'"
        )

    # Any genuine mismatch immediately results in CHANGES_REQUESTED.
    if comments:
        return ComparisonResult(status="CHANGES_REQUESTED", comments=comments, extracted=extracted)
    # Only unresolved amount uncertainty remains → defer to a human.
    if review_comments:
        return ComparisonResult(status="NEEDS_REVIEW", comments=review_comments, extracted=extracted)
    return ComparisonResult(status="APPROVED", comments=[], extracted=extracted)
