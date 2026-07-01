# Comparator — takes what the model extracted from the document and compares it
# against what the system says it should be.
#
# Each field type uses a different comparison strategy:
#   - Names, banks, branches, loan types  →  fuzzy match (handles casing / abbreviations)
#   - Loan account number, application ID →  exact match (one wrong digit = wrong record)
#   - Amounts                             →  normalize to float + digit/word cross-check
#   - Dates                               →  normalize to YYYY-MM-DD then compare
#
# Returns one of three statuses:
#   APPROVED          — everything matched
#   CHANGES_REQUESTED — one or more fields are wrong
#   NEEDS_REVIEW      — amounts are ambiguous (digit/word conflict), send to a human

from dataclasses import dataclass, field
from rapidfuzz import fuzz
from normalizer import normalize_amount, normalize_date, normalize_text, words_to_number
from config import (
    FUZZY_FIELDS, EXACT_FIELDS, AMOUNT_FIELDS, DATE_FIELDS,
    FUZZY_THRESHOLDS, INVALID_DOC_MIN_FIELDS, FIELDS, AMOUNT_WORD_FIELDS,
)


@dataclass
class ComparisonResult:
    """What compare_fields() returns — the final verdict plus supporting detail."""
    status:   str
    comments: list[str] = field(default_factory=list)
    extracted: dict     = field(default_factory=dict)


def _field_label(field_key: str) -> str:
    """Turn a snake_case key into a readable label. sanction_amount → Sanction Amount"""
    return field_key.replace("_", " ").title()


def _is_valid_document(extracted: dict) -> bool:
    """Check that the document had enough readable content to be worth comparing.

    If fewer than 3 fields came back non-empty, the upload was probably a blank
    page, a photo of something unrelated, or a completely failed OCR.
    """
    found = sum(1 for v in extracted.values() if v is not None and str(v).strip())
    return found >= INVALID_DOC_MIN_FIELDS


def _amounts_close(a, b) -> bool:
    """True if two floats are within a penny of each other (floating point safety)."""
    return a is not None and b is not None and abs(a - b) < 0.01


def _scale_factor(a, b) -> bool:
    """True when two amounts differ by exactly 10x, 100x, or 1000x.

    This pattern — where one number is exactly 10 times the other — means the
    model likely dropped or added a zero while reading the digits. It's the
    most common OCR mistake on large Indian numbers.
    """
    if not a or not b:
        return False
    hi, lo = (a, b) if a > b else (b, a)
    ratio = hi / lo
    return any(abs(ratio - f) < 0.01 for f in (10, 100, 1000))


def _reconcile_amount(digit_str, word_str) -> tuple[float | None, bool]:
    """Cross-check the digit version of an amount against the words version.

    Indian loan documents print amounts twice — "Rs.63.50 lakhs" and
    "Rupees Sixty Three Lakh Fifty Thousand Only". If the model misread a digit,
    the words version is usually still correct and can recover the right value.

    Returns (best_value, conflict):
      - best_value: the most trustworthy reading we could get
      - conflict: True if digits and words disagree in a way we can't explain
                  (meaning a human needs to look at this)

    Decision logic:
      words missing          → trust digits alone
      digits missing         → trust words alone
      both agree             → use digits (they're the same)
      differ by 10x/100x     → digits dropped a zero; words win
      differ in any other way → genuine conflict → (None, True)
    """
    d = normalize_amount(str(digit_str)) if digit_str else None
    w = words_to_number(str(word_str))  if word_str  else None

    if d is None and w is None:
        return None, False
    if w is None:
        return d, False   # no words — just use digits
    if d is None:
        return w, False   # no digits — just use words
    if _amounts_close(d, w):
        return d, False   # both say the same thing — great
    if _scale_factor(d, w):
        return w, False   # words recover the dropped/added zero
    return None, True     # can't explain the difference — flag for human review


def _fields_match(field_key: str, extracted_val, expected_val) -> bool:
    """Check whether one extracted field value matches the expected value.

    Uses the right comparison strategy for each field type.
    Returns False if extracted_val is missing — a missing value never matches.
    """
    if extracted_val is None or str(extracted_val).strip() == "":
        return False

    if field_key in AMOUNT_FIELDS:
        # Both values normalized to floats before comparing
        e = normalize_amount(str(extracted_val))
        x = normalize_amount(str(expected_val))
        if e is None or x is None:
            return False
        return e == x

    if field_key in DATE_FIELDS:
        # Both dates converted to YYYY-MM-DD before comparing
        e = normalize_date(str(extracted_val))
        x = normalize_date(str(expected_val))
        if e is None or x is None:
            return False
        return e == x

    if field_key in EXACT_FIELDS:
        e = str(extracted_val).strip()
        x = str(expected_val).strip()
        # Some lenders prefix the ID with extra text (e.g. "AHFLN No. 337887565").
        # We accept a match if the extracted value ends with the expected ID.
        return e == x or e.endswith(x)

    if field_key in FUZZY_FIELDS:
        # Fuzzy match — how similar are the two strings on a 0-100 scale?
        threshold = FUZZY_THRESHOLDS.get(field_key, 80)
        score = fuzz.ratio(
            normalize_text(str(extracted_val)),
            normalize_text(str(expected_val)),
        )
        return score >= threshold

    # Default — fuzzy at 80 for anything not explicitly categorised
    score = fuzz.ratio(
        normalize_text(str(extracted_val)),
        normalize_text(str(expected_val)),
    )
    return score >= 80


def _compare_amount(f: str, extracted: dict, expected_val) -> tuple[str, str]:
    """Run the full digit + word reconciliation for one amount field.

    Returns (outcome, comment):
      outcome = 'match'    → values agree, no comment needed
      outcome = 'mismatch' → values disagree, add to CHANGES_REQUESTED
      outcome = 'review'   → can't resolve, add to NEEDS_REVIEW
    """
    label     = _field_label(f)
    digit_str = extracted.get(f)
    word_str  = extracted.get(AMOUNT_WORD_FIELDS[f])
    exp_num   = normalize_amount(str(expected_val))

    value, conflict = _reconcile_amount(digit_str, word_str)

    if conflict:
        # Digits and words disagree. Before flagging for review, check whether either
        # one matches the expected value — if so, that reading is likely correct and
        # the other is a misread.
        d = normalize_amount(str(digit_str)) if digit_str else None
        w = words_to_number(str(word_str)) if word_str else None
        if _amounts_close(w, exp_num):
            return "match", ""   # words correct, digits misread — trust words
        if _amounts_close(d, exp_num):
            return "match", ""   # digits correct, words misread — trust digits
        return "review", (
            f"{label} unclear: digits '{digit_str}' and words '{word_str}' disagree "
            f"on the document. Please verify manually."
        )

    if _amounts_close(value, exp_num):
        return "match", ""

    # Reconciled value doesn't match the expected amount.
    # Special case: if we had no words and the digits are off by exactly 10x,
    # it's probably a misread zero — defer to human rather than hard-reject.
    word_num  = words_to_number(str(word_str)) if word_str else None
    digit_num = normalize_amount(str(digit_str)) if digit_str else None
    if word_num is None and _scale_factor(digit_num, exp_num):
        return "review", (
            f"{label} digit error: document shows '{digit_str}', expected "
            f"'{expected_val}' (off by a factor of 10 — likely a misread zero, "
            f"no amount-in-words to confirm). Please verify manually."
        )

    return "mismatch", (
        f"{label} mismatch: document shows '{digit_str}', expected '{expected_val}'"
    )


def compare_fields(extracted: dict, expected: dict) -> ComparisonResult:
    """Compare every extracted field against its expected value and return a verdict.

    Goes through each field in order. Mismatches go into the comments list.
    Amount fields with unresolvable uncertainty go into review_comments.

    Final status:
      - Any genuine mismatch           → CHANGES_REQUESTED (even if amounts are uncertain)
      - No mismatches, but amount doubt → NEEDS_REVIEW
      - Everything clean               → APPROVED
    """
    if not _is_valid_document(extracted):
        return ComparisonResult(
            status="CHANGES_REQUESTED",
            comments=["Invalid document uploaded. Please upload a valid sanctioned letter, "
                      "disbursement letter, or banker confirmation."],
            extracted=extracted,
        )

    comments        = []  # hard mismatches → CHANGES_REQUESTED
    review_comments = []  # amount uncertainty → NEEDS_REVIEW

    for f in FIELDS:
        expected_val = expected.get(f)
        if not expected_val:
            # No expected value for this field — skip it, nothing to compare against
            continue

        if f in AMOUNT_FIELDS:
            outcome, comment = _compare_amount(f, extracted, expected_val)
            if outcome == "match":
                continue
            (review_comments if outcome == "review" else comments).append(comment)
            continue

        if _fields_match(f, extracted.get(f), expected_val):
            continue

        # Field doesn't match — record what was found vs what was expected
        comments.append(
            f"{_field_label(f)} mismatch: document shows '{extracted.get(f)}', "
            f"expected '{expected_val}'"
        )

    if comments:
        # Hard mismatches always win — document must go back for corrections
        return ComparisonResult(status="CHANGES_REQUESTED", comments=comments, extracted=extracted)
    if review_comments:
        # No hard mismatches, but we couldn't resolve the amounts — send to a human
        return ComparisonResult(status="NEEDS_REVIEW", comments=review_comments, extracted=extracted)

    return ComparisonResult(status="APPROVED", comments=[], extracted=extracted)
