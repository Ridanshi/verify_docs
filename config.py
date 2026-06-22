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

# The vision-language model we're using. 32B is needed for reliable digit/OCR accuracy on Indian documents.
VLM_MODEL_ID = "Qwen/Qwen2.5-VL-32B-Instruct"

# How many tokens the model can generate in its response (the JSON output).
# 512 is more than enough for our 11-field JSON.
VLM_MAX_NEW_TOKENS = 512
