import pytest
from normalizer import normalize_amount, normalize_date, normalize_text


def test_amount_lakhs():
    assert normalize_amount("Rs.195.00 lakhs") == 19500000.0

def test_amount_lakh_singular():
    assert normalize_amount("Rs.1.5 lakh") == 150000.0

def test_amount_rupee_symbol():
    assert normalize_amount("₹63,50,000.00") == 6350000.0

def test_amount_plain():
    assert normalize_amount("6350000") == 6350000.0

def test_amount_crore():
    assert normalize_amount("Rs.1.5 crore") == 15000000.0

def test_amount_none():
    assert normalize_amount(None) is None

def test_amount_empty():
    assert normalize_amount("") is None

def test_date_dot_format():
    assert normalize_date("04.02.2026") == "2026-02-04"

def test_date_written():
    assert normalize_date("31 Jan 2026") == "2026-01-31"

def test_date_iso():
    assert normalize_date("2026-01-31") == "2026-01-31"

def test_date_none():
    assert normalize_date(None) is None

def test_date_invalid():
    assert normalize_date("not a date") is None

def test_text_casing():
    assert normalize_text("ZAINAB MEDICALS") == "zainab medicals"

def test_text_whitespace():
    assert normalize_text("  Mount Road  ") == "mount road"

def test_text_none():
    assert normalize_text(None) == ""
