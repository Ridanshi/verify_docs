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

FUZZY_FIELDS = {"customer_name", "bank_name", "branch", "loan_type"}
EXACT_FIELDS = {"loan_account_number", "application_id"}
AMOUNT_FIELDS = {"sanction_amount", "disbursement_amount"}
DATE_FIELDS = {"disbursement_date"}

FUZZY_THRESHOLDS = {
    "customer_name": 85,
    "bank_name": 80,
    "branch": 80,
    "loan_type": 80,
}

INVALID_DOC_MIN_FIELDS = 3
VLM_MODEL_ID = "Qwen/Qwen2.5-VL-32B-Instruct"
VLM_MAX_NEW_TOKENS = 512
