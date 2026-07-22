# Central config file — every other module imports from here.
# If you want to change a threshold, swap the model, or add a new field, this is the only file you need to touch.

# All 9 fields we extract from every loan document and verify against the system.
FIELDS = [
    "customer_name",
    "loan_account_number",
    "application_id",
    "sanction_amount",
    "disbursement_amount",
    "loan_type",
    "branch",
    "bank_name",
    "disbursement_date",
]

# Names, banks, branches, and loan types can be written slightly differently
# (e.g. "T.Nagar" vs "T. Nagar") — fuzzy matching handles that.
FUZZY_FIELDS = {"customer_name", "bank_name", "branch", "loan_type"}

# Loan account numbers and application IDs must match exactly.
# Even one wrong digit means a completely different loan or customer.
EXACT_FIELDS = {"loan_account_number", "application_id"}

AMOUNT_FIELDS = {"sanction_amount", "disbursement_amount"}
DATE_FIELDS   = {"disbursement_date"}

# Indian loan documents print amounts twice — once in digits, once in words
# (e.g. "Rs.63.50 lakhs (Rupees Sixty Three Lakh Fifty Thousand Only)").
# We extract both. If the model misreads a digit, the words version can correct it.
AMOUNT_WORD_FIELDS = {
    "sanction_amount":     "sanction_amount_words",
    "disbursement_amount": "disbursement_amount_words",
}

# How similar two strings need to be before we call them a match (0-100).
# 85 for names because co-applicants and suffixes make exact matches rare.
# 80 for everything else — tight enough to catch real mismatches, loose enough for formatting noise.
FUZZY_THRESHOLDS = {
    "customer_name": 85,
    "bank_name":     80,
    "branch":        80,
    "loan_type":     80,
}

# If fewer than 3 fields were extracted, the document is probably invalid or unreadable.
INVALID_DOC_MIN_FIELDS = 3

# The vision-language model we're using. 7B fits on a single T4 (~5-6GB in 4-bit)
# and leaves ample headroom, so Kaggle sessions stay stable across many uploads.
# 32B is more accurate (see prior stress-test results) but on Kaggle free-tier
# the kernel dies unpredictably under the tighter memory budget — 7B trades a
# small accuracy hit for reliability we can actually demo with. Swap back to
# "Qwen/Qwen2.5-VL-32B-Instruct" once running on hardware with >=24GB VRAM.
VLM_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

# How many tokens the model can generate in its response (the JSON output).
# 512 is more than enough for our 11-field JSON.
VLM_MAX_NEW_TOKENS = 512


# ── Lender LAN patterns ────────────────────────────────────────────────────────
#
# Every lender formats its Loan Account Number differently. Before trusting a
# VLM-extracted LAN we validate it against the known patterns for our lenders —
# a value that matches no pattern is almost certainly an OCR error and should
# not hit the database.

import re as _re

LAN_PATTERNS = {
    "mahindra": r"^LAPSEC\d{9}$",     # e.g. LAPSEC954654015
    "aadhar":   r"^\d{9}$",           # e.g. 337887565
    "hdfc":     r"^HL\d{10}$",        # e.g. HL1234567890
    "ap":       r"^AP\d{10}$",        # e.g. AP0020067658
}


def matches_any_lender_pattern(lan: str) -> bool:
    """True if the given LAN matches at least one known lender's format."""
    if not lan:
        return False
    return any(_re.fullmatch(p, lan.strip()) for p in LAN_PATTERNS.values())
