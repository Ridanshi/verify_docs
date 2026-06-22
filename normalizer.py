# Normalizer — converts raw text extracted from documents into standard formats.
#
# The model copies values exactly as printed (e.g. "Rs.63.50 lakhs", "31 Jan 2026").
# Before we can compare them against the system's values, we need everything in
# the same format. That's what this file does.

import re
from dateutil import parser as dateparser


def normalize_amount(value: str) -> float | None:
    """Convert any Indian rupee amount string into a plain float.

    Handles: Rs., ₹, lakhs, crores, Indian comma format (e.g. 63,50,000).
    Returns None if the value is empty or can't be parsed.

    Examples:
        "Rs.63.50 lakhs"  →  6350000.0
        "₹63,50,000.00"   →  6350000.0
        "6350000"         →  6350000.0
    """
    if not value:
        return None
    value = str(value).lower().strip()

    # Strip currency symbols and commas — they vary too much across documents
    value = value.replace("rs.", "").replace("₹", "").replace(",", "").strip()

    try:
        if "crore" in value:
            num = float(re.sub(r"[^\d.]", "", value))
            return round(num * 10_000_000, 2)
        if "lakh" in value:
            num = float(re.sub(r"[^\d.]", "", value))
            return round(num * 100_000, 2)
        # No unit word — treat as a plain number (e.g. "6350000")
        return float(re.sub(r"[^\d.]", "", value))
    except (ValueError, TypeError):
        return None


# Number words (ones and tens) — used by words_to_number below
_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Scale words — multiply the running total by these
_WORD_SCALES = {
    "hundred":  100,
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000,
}


def words_to_number(value: str) -> float | None:
    """Parse an Indian amount written in words into a number.

    Indian docs print amounts like "Rupees Sixty Three Lakh Fifty Thousand Only".
    This function converts that to 6350000.0.

    Filler words ("Rupees", "Only", "and") are simply ignored.
    Returns None if no recognisable number words are found.

    Note: we never strip "and" as a substring — it would corrupt "thousand".
    """
    if not value:
        return None
    s = str(value).lower()

    # Clean up punctuation; filler words like "rupees" and "only" just fall
    # through as unknown tokens and get ignored automatically
    s = s.replace("/-", " ").replace("-", " ").replace("₹", " ")
    tokens = [t for t in re.split(r"[\s,.]+", s) if t]

    total   = 0     # final accumulated value
    current = 0     # running sub-total for the current group
    saw_number = False

    for tok in tokens:
        if tok in _WORD_UNITS:
            current += _WORD_UNITS[tok]
            saw_number = True
        elif tok == "hundred":
            current = (current or 1) * 100
            saw_number = True
        elif tok in _WORD_SCALES:
            # Scale words (lakh, crore, thousand) flush the current group into total
            current = (current or 1) * _WORD_SCALES[tok]
            total  += current
            current = 0
            saw_number = True
        # Unknown token → skip it silently

    if not saw_number:
        return None
    return float(total + current)


# Quick check for already-ISO dates (YYYY-MM-DD) — these don't need dayfirst logic
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_date(value: str) -> str | None:
    """Convert any date format into YYYY-MM-DD for consistent comparison.

    Handles: "31 Jan 2026", "31.01.2026", "31/01/2026", "2026-01-31".
    Returns None if the string can't be parsed as a date.

    We special-case ISO format because dateparser's dayfirst=True would
    incorrectly swap month and day on a date like "2026-06-01".
    """
    if not value:
        return None
    s = str(value).strip()
    try:
        if _ISO_DATE.match(s):
            # Already in ISO format — parse directly, no ambiguity
            return dateparser.parse(s).strftime("%Y-%m-%d")
        # All other formats (DD Mon YYYY, DD.MM.YYYY, etc.) — day comes first in India
        return dateparser.parse(s, dayfirst=True).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_text(value: str) -> str:
    """Lowercase and strip a string so comparisons aren't thrown off by casing.

    "ZAINAB MEDICALS" and "Zainab Medicals" should be treated as the same.
    """
    if not value:
        return ""
    return str(value).lower().strip()
