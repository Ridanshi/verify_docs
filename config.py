# List of all fields that must be extracted from a document and verified against expected values.
FIELDS = [
    "customer_name",
    "bank_name",
    "loan_account_number",
    "application_id",
    "sanction_amount",
    "disbursement_amount",
    "loan_type",
    "branch",
    "disbursement_date",
]

FUZZY_FIELDS = {"customer_name", "bank_name", "branch", "loan_type"} # Fields compared using fuzzy matching.
EXACT_FIELDS = {"loan_account_number", "application_id"} # Fields that uniquely identify a loan/application.
AMOUNT_FIELDS = {"sanction_amount", "disbursement_amount"}
DATE_FIELDS = {"disbursement_date"}

# Each amount field has a words counterpart extracted from the document
# (e.g. "Rupees Twenty Five Lakhs Only"). Words rarely mis-OCR, so they
# recover dropped/added zeros in the digits — cross-checked in comparator.
AMOUNT_WORD_FIELDS = {
    "sanction_amount":     "sanction_amount_words",
    "disbursement_amount": "disbursement_amount_words",
}

# Minimum fuzzy-match similarity scores required for a field to be considered a match.
FUZZY_THRESHOLDS = {
    "customer_name": 85,
    "bank_name": 80,
    "branch": 80,
    "loan_type": 80,
}

INVALID_DOC_MIN_FIELDS = 3 # Minimum number of successfully extracted non-empty fields required for a document to be considered valid.
VLM_MODEL_ID = "Qwen/Qwen2.5-VL-32B-Instruct"
VLM_MAX_NEW_TOKENS = 512
