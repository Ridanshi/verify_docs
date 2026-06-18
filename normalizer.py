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
