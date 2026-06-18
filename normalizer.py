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


def normalize_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return dateparser.parse(str(value), dayfirst=True).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_text(value: str) -> str:
    if not value:
        return ""
    return str(value).lower().strip()
