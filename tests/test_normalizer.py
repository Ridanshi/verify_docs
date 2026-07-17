import pytest
from normalizer import normalize_amount, normalize_date, normalize_text, words_to_number


def test_words_simple_lakhs():
    assert words_to_number("Rupees Twenty Five Lakhs Only") == 2500000.0

def test_words_lakh_and_thousand():
    assert words_to_number("Rupees Sixty Three Lakh Fifty Thousand Only") == 6350000.0

def test_words_crore():
    assert words_to_number("Rupees Two Crore Only") == 20000000.0

def test_words_crore_and_lakh():
    assert words_to_number("Rupees One Crore Fifty Lakhs Only") == 15000000.0

def test_words_and_does_not_corrupt_thousand():
    # regression: stripping "and" must not break "thousand"
    assert words_to_number("Five Lakh Seventy Five Thousand") == 575000.0

def test_words_no_number_returns_none():
    assert words_to_number("not an amount") is None

def test_words_empty_returns_none():
    assert words_to_number("") is None


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

def test_text_limited_matches_ltd():
    assert normalize_text("Aadhar Housing Finance Limited") == normalize_text("Aadhar Housing Finance Ltd.")

def test_text_ltd_trailing_period_stripped():
    assert normalize_text("HDFC Ltd") == normalize_text("HDFC Ltd.")

def test_text_private_limited_matches_pvt_ltd():
    assert normalize_text("ABC Finance Private Limited") == normalize_text("ABC Finance Pvt. Ltd.")

def test_text_company_suffix_does_not_affect_plain_names():
    # a generalized fix shouldn't accidentally mangle names with no legal suffix
    assert normalize_text("Mount Road") == "mount road"
    assert normalize_text("Zainab Medicals") == "zainab medicals"
