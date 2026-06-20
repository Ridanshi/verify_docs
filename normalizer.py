import re
from dateutil import parser as dateparser


def normalize_amount(value: str) -> float | None:
    if not value:
        return None
    value = str(value).lower().strip()
    value = value.replace("rs.", "").replace("₹", "").replace(",", "").strip()
    try:
        if "crore" in value:
            num = float(re.sub(r"[^\d.]", "", value))
            return round(num * 10_000_000, 2)
        if "lakh" in value:
            num = float(re.sub(r"[^\d.]", "", value))
            return round(num * 100_000, 2)
        return float(re.sub(r"[^\d.]", "", value))
    except (ValueError, TypeError):
        return None


_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000,
}


def words_to_number(value: str) -> float | None:
    """Parse an Indian amount-in-words to a number.
    "Rupees Twenty Five Lakhs Only" -> 2500000
    "Sixty Three Lakh Fifty Thousand" -> 6350000
    Returns None if no number words are found."""
    if not value:
        return None
    s = str(value).lower()
    # normalise punctuation to spaces; filler/currency words fall through as
    # unknown tokens and are ignored. ("and" must NOT be stripped as a
    # substring — it would corrupt "thousand".)
    s = s.replace("/-", " ").replace("-", " ").replace("₹", " ")
    tokens = [t for t in re.split(r"[\s,.]+", s) if t]

    total = 0           # accumulated whole value
    current = 0         # running group being built
    saw_number = False
    for tok in tokens:
        if tok in _WORD_UNITS:
            current += _WORD_UNITS[tok]
            saw_number = True
        elif tok == "hundred":
            current = (current or 1) * 100
            saw_number = True
        elif tok in _WORD_SCALES:
            current = (current or 1) * _WORD_SCALES[tok]
            total += current
            current = 0
            saw_number = True
        # unknown token → ignore (handles stray words)
    if not saw_number:
        return None
    return float(total + current)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def normalize_date(value: str) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        # ISO format YYYY-MM-DD is unambiguous — don't apply dayfirst
        if _ISO_DATE.match(s):
            return dateparser.parse(s).strftime("%Y-%m-%d")
        # All other formats (DD Mon YYYY, DD/MM/YYYY, DD.MM.YYYY) use dayfirst
        return dateparser.parse(s, dayfirst=True).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_text(value: str) -> str:
    if not value:
        return ""
    return str(value).lower().strip()
