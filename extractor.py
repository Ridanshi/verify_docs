# Extractor — loads the vision-language model and uses it to read fields from
# loan document images.
#
# The model (Qwen2.5-VL — 7B by default, 32B optional) is a vision-language AI
# that understands both images and text. We send it an image + a set of
# instructions (the PROMPT), and it returns a JSON object with all the field
# values it found in the document.
#
# The model is loaded lazily — it's only pulled into memory the first time
# extract_fields() is called, not when the module is imported.

import json
import os
import re
import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info  # Qwen helper for preparing image inputs
from config import VLM_MODEL_ID, VLM_MAX_NEW_TOKENS, FIELDS, AMOUNT_WORD_FIELDS

# These are module-level so the model stays in GPU memory between calls.
# Loading takes 5-10 minutes; inference per document takes ~2 minutes.
_model     = None
_processor = None

# 4-bit quantization slashes VRAM footprint. 7B → ~5GB, 32B → ~18GB.
# Always on by default — 32B needs it on T4 x2, and 7B still benefits.
_USE_4BIT = os.environ.get("USE_4BIT", "1") == "1"


def _load_model():
    """Load the model into GPU memory (only runs once per session)."""
    global _model, _processor
    if _model is not None:
        return  # already loaded

    num_gpus = torch.cuda.device_count()
    if num_gpus == 0:
        raise RuntimeError(
            "No CUDA GPU detected. This model requires a GPU with ≥8GB VRAM. "
            "Run on Kaggle T4 x2 or a cloud GPU instance."
        )

    # Cap each GPU at 13GB so, when running 32B, the model splits evenly across
    # both T4s on Kaggle. 7B fits entirely on GPU 0 — device_map="auto" places
    # it there and leaves GPU 1 idle. Setting cpu to 0GiB blocks CPU offload —
    # 4-bit kernels can't run on CPU.
    max_memory = {i: "13GiB" for i in range(num_gpus)}
    max_memory["cpu"] = "0GiB"

    try:
        if _USE_4BIT:
            bnb_config = BitsAndBytesConfig(load_in_4bit=True)
            _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                VLM_MODEL_ID,
                quantization_config=bnb_config,
                device_map="auto",
                max_memory=max_memory,
            )
        else:
            # float16 — only viable on GPUs with ≥40GB VRAM (e.g. A100)
            _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                VLM_MODEL_ID,
                torch_dtype=torch.float16,
                device_map="auto",
                max_memory=max_memory,
            )
        _processor = AutoProcessor.from_pretrained(VLM_MODEL_ID)

    except Exception:
        # If loading fails halfway, clear everything so the next call starts clean.
        # Without this, partial GPU allocations would cause OOM on retry.
        _model     = None
        _processor = None
        torch.cuda.empty_cache()
        raise


# ── Prompts ────────────────────────────────────────────────────────────────────
#
# These are the written instructions we send to the model along with the image.
# The model reads the image + the prompt and returns a JSON object.
#
# Key principle: we ask the model to copy values EXACTLY as they appear.
# All conversion (amounts → floats, dates → ISO) is done in normalizer.py, not here.
# This avoids the model doing arithmetic and getting it wrong.

PROMPT = """You are a financial document extraction assistant for Indian loan documents.

Step 1: Identify the document type — one of:
  sanctioned_letter, disbursement_letter, offer_letter, banker_confirmation, invalid

If this image is not a financial document (photo of objects, people, or unrelated content),
set document_type to "invalid" and all fields to null.

Step 2: Extract exactly these 9 fields. Read each definition carefully before extracting.

  customer_name       — Full name of the loan applicant/borrower. Usually appears after
                        "Dear", "To", "Borrower Name", or "Customer Name".

  bank_name           — Name of the lending institution (the company issuing this letter),
                        e.g. "ABC Finance Ltd", "XYZ Housing Finance". This is the
                        organisation's name, NOT a street address, city, or branch name.

  loan_account_number — The loan account number for this disbursement. Usually labelled
                        "Loan Account No", "Account Number", "LAP No", "LAN", "LAN Number",
                        "App/LAN Number", or "Loan A/c No". It is a unique identifier
                        for the loan itself, different from the application ID.
                        Note: a label like "App/LAN Number" contains the LAN value, not
                        the application ID — extract it as loan_account_number.
                        Read it character by character — do not skip, add, or transpose a
                        single digit. Watch closely for commonly confused digit pairs
                        (6/8, 1/7, 0/8, 3/8, 5/6) and count the total digit length twice
                        before answering.

  application_id      — The loan application reference number. Usually labelled
                        "Application No", "Application ID", or "Ref No". It identifies
                        the application, not the loan account.
                        Read it character by character — do not skip, add, or transpose a
                        single digit. Watch closely for commonly confused digit pairs
                        (6/8, 1/7, 0/8, 3/8, 5/6) and count the total digit length twice
                        before answering.

  sanction_amount     — The total loan amount sanctioned/approved, in DIGITS. Copy the
                        amount EXACTLY as it appears — same digits, same format, same
                        symbols. Do NOT convert, round, or do any math.
                        Count the digits carefully — do NOT drop or add a zero.
                        Indian comma format groups differently from Western:
                        "25,00,000" = 25 lakhs = twenty-five lakh (7 digits).
                        Preserve every digit and every comma exactly as printed.
                        Examples (copy verbatim):
                          "₹25,00,000"        →  "₹25,00,000"
                          "Rs.25.00 lakhs"    →  "Rs.25.00 lakhs"
                          "₹2,00,00,000"      →  "₹2,00,00,000"
                          "Rs. 1,50,00,000/-" →  "Rs. 1,50,00,000/-"

  sanction_amount_words — The same sanctioned amount written IN WORDS, usually printed
                        in brackets after the digits, e.g. "(Rupees Twenty Five Lakhs
                        Only)". Copy the words exactly. Set to null if no words version
                        is printed on the document.

  disbursement_amount — The amount actually disbursed, in DIGITS. Copy EXACTLY as written,
                        same rules as sanction_amount — no conversion, no math.

  disbursement_amount_words — The disbursed amount written IN WORDS, if printed in
                        brackets. Copy exactly. Set to null if absent.

  loan_type           — Category of loan, e.g. "Home Loan", "SME Loan", "Mortgage Loan",
                        "Loan Against Property". Extract as written.

  branch              — The branch name or city where the loan is being processed.
                        Usually labelled "Branch", "Branch Office", or "Processing Centre".

  disbursement_date   — The disbursement date. Copy it EXACTLY as written, character
                        for character (e.g. "19 Jun 2026", "19.06.2026", "2026-06-19").
                        Do NOT reformat or change the order of day/month/year.
                        This is the DISBURSEMENT date — not the sanction date, offer
                        date, or any other date on the page.

Set a field to null only if it is genuinely absent from the document.

Return ONLY valid JSON, no explanation:
{
  "document_type": "...",
  "fields": {
    "customer_name": "...",
    "bank_name": "...",
    "loan_account_number": "...",
    "application_id": "...",
    "sanction_amount": "...",
    "sanction_amount_words": "...",
    "disbursement_amount": "...",
    "disbursement_amount_words": "...",
    "loan_type": "...",
    "branch": "...",
    "disbursement_date": "..."
  }
}"""

# Same as PROMPT but with a harder reminder — used on the retry if the first
# response wasn't valid JSON
STRICT_PROMPT = PROMPT + "\n\nIMPORTANT: Return ONLY the JSON object. No text before or after."

# ── Auto Compare prompts ────────────────────────────────────────────────────────
# Used when the user uploads a combined screenshot (system panel on the left,
# loan document on the right). Two separate model calls read each side.

SYSTEM_PANEL_PROMPT = """You are looking at a screenshot of a loan management system.

Focus ONLY on the LEFT panel of this screenshot — it shows the system's stored loan record with labeled fields.

Extract these fields from the LEFT panel labels and their values:

  customer_name       — value next to "Customer Name"
  bank_name           — value next to "Bank"
  loan_account_number — value next to "Loan Account Number" (copy every character; ignore annotations like "15 digits")
  application_id      — value next to "Application ID" (digits only; ignore annotations like "5 digits")
  sanction_amount     — value next to "Sanction Amount"
  disbursement_amount — value next to "Disbursement Amount"
  loan_type           — value next to "Type of Loan"
  branch              — value next to "Branch Location" or "Branch"
  disbursement_date   — value next to "Date of Disbursement"

Set a field to null only if the label is absent or its value is blank / dash.

Return ONLY valid JSON, no explanation:
{
  "customer_name": "...",
  "bank_name": "...",
  "loan_account_number": "...",
  "application_id": "...",
  "sanction_amount": "...",
  "disbursement_amount": "...",
  "loan_type": "...",
  "branch": "...",
  "disbursement_date": "..."
}"""

# The document prompt is the same as the main PROMPT, but we tell the model
# to ignore the left panel (system UI) and only read the document on the right.
DOC_PANEL_PROMPT = (
    "You are looking at a screenshot that shows a loan document on the RIGHT side.\n\n"
    "Focus ONLY on the loan document visible in the RIGHT panel of this screenshot "
    "— ignore the left panel entirely.\n\n"
    + PROMPT
)

# ── Amount-only refinement prompt ────────────────────────────────────────────────
# Small print on amounts is the main cause of digit-drop errors (e.g. reading
# ₹6,50,000 instead of ₹65,00,000). This second, narrower prompt asks the model
# to focus purely on the four amount-related fields, on a higher-resolution
# render of the same document (see preprocessor.load_image_high_res). Splitting
# this into its own focused call — rather than asking for all 9 fields at once —
# gives the model less to split attention across for this specific weak spot.
AMOUNT_FOCUS_PROMPT = """You are a financial document extraction assistant. Read this
Indian loan document image VERY carefully, focusing only on monetary amounts.

Extract exactly these 4 fields:

  sanction_amount     — The total loan amount sanctioned/approved, in DIGITS.
                        Copy EXACTLY as printed — same digits, same commas, same
                        symbols. Count every digit twice before answering. Indian
                        comma grouping: "25,00,000" = twenty-five lakh (7 digits).
                        Do NOT drop, add, or transpose a single digit.

  sanction_amount_words — The same amount written IN WORDS, usually in brackets
                        after the digits, e.g. "(Rupees Twenty Five Lakhs Only)".
                        Copy exactly. Set to null if no words version is printed.

  disbursement_amount — The amount actually disbursed, in DIGITS. Same precision
                        rules as sanction_amount.

  disbursement_amount_words — The disbursed amount in words, if printed in
                        brackets. Copy exactly. Set to null if absent.

Set a field to null only if it is genuinely absent from the document.

Return ONLY valid JSON, no explanation:
{
  "sanction_amount": "...",
  "sanction_amount_words": "...",
  "disbursement_amount": "...",
  "disbursement_amount_words": "..."
}"""

_AMOUNT_KEYS = ["sanction_amount", "sanction_amount_words", "disbursement_amount", "disbursement_amount_words"]


# ── Model helpers ───────────────────────────────────────────────────────────────

def _call_model(image: Image.Image, prompt: str) -> str:
    """Send one image + one prompt to the model and return the raw text response."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text",  "text":  prompt},
            ],
        }
    ]

    # Convert to Qwen's internal chat format
    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    # Prepare image tensors
    image_inputs, video_inputs = process_vision_info(messages)

    # Move everything to the GPU(s) the model is on
    inputs = _processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(_model.device)

    with torch.no_grad():
        generated_ids = _model.generate(**inputs, max_new_tokens=VLM_MAX_NEW_TOKENS)

    # Slice off the input tokens — we only want the newly generated response
    input_len  = inputs["input_ids"].shape[1]
    new_tokens = generated_ids[:, input_len:]
    return _processor.batch_decode(new_tokens, skip_special_tokens=True)[0]


def _parse_json(raw: str) -> dict | None:
    """Pull a JSON object out of the model's raw text response.

    The model sometimes adds a sentence before or after the JSON.
    We use a regex to find the outermost { ... } block and parse that.
    Returns None if no valid JSON is found.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# The 9 core fields + 2 amount-in-words fields = 11 total keys we track
_ALL_KEYS = FIELDS + list(AMOUNT_WORD_FIELDS.values())


def _empty_fields() -> dict:
    """Return a dict with all 11 fields set to None.
    Used when extraction fails or the document is invalid."""
    return {k: None for k in _ALL_KEYS}


def _clean(val) -> str | None:
    """Strip whitespace and convert the string "null" to Python None."""
    return str(val).strip() if val and str(val).strip().lower() != "null" else None


# ── Public extraction functions ─────────────────────────────────────────────────

def extract_fields(image: Image.Image) -> dict:
    """Extract all 11 fields from a single loan document image.

    Tries once with the standard prompt. If the response isn't valid JSON,
    retries once with a stricter version of the prompt.
    Returns a dict with all fields (some may be None if absent from the doc).
    """
    _load_model()

    raw    = _call_model(image, PROMPT)
    parsed = _parse_json(raw)

    if parsed is None:
        # First attempt failed — try again with a harder instruction
        raw    = _call_model(image, STRICT_PROMPT)
        parsed = _parse_json(raw)

    if parsed is None:
        return _empty_fields()

    if parsed.get("document_type") == "invalid":
        return _empty_fields()

    fields = parsed.get("fields", {})
    result = _empty_fields()
    for key in _ALL_KEYS:
        result[key] = _clean(fields.get(key))

    return result


def refine_amount_fields(image_high_res: Image.Image, extracted: dict) -> dict:
    """Re-read just the amount fields on a higher-resolution render of the same
    document, to catch digit-drop errors from the main extract_fields() pass.

    Returns a NEW dict: a copy of `extracted` with the 4 amount keys overwritten
    by this pass's reading — unless this pass itself failed to parse a JSON
    response, in which case the original values are kept (never silently drop
    a good reading in favor of a failed one).
    """
    _load_model()

    raw    = _call_model(image_high_res, AMOUNT_FOCUS_PROMPT)
    parsed = _parse_json(raw)

    if parsed is None:
        return dict(extracted)  # refinement pass failed — keep the original reading

    result = dict(extracted)
    for key in _AMOUNT_KEYS:
        result[key] = _clean(parsed.get(key))

    return result


def extract_system_fields(image: Image.Image) -> dict:
    """Extract system/CRM values from the LEFT panel of a combined screenshot.

    Used internally by extract_from_combined_screenshot().
    Returns a dict of the 9 core fields (no amount-in-words needed here —
    the system already stores clean values).
    """
    _load_model()
    raw    = _call_model(image, SYSTEM_PANEL_PROMPT)
    parsed = _parse_json(raw)
    if parsed is None:
        return {k: None for k in FIELDS}
    result = {k: None for k in FIELDS}
    for key in FIELDS:
        result[key] = _clean(parsed.get(key))
    return result


def extract_from_combined_screenshot(image: Image.Image) -> tuple[dict, dict]:
    """Extract both sides of a combined system + document screenshot.

    Call 1: reads the LEFT panel (CRM/system) → what the system says
    Call 2: reads the RIGHT panel (loan document) → what the document says

    Returns (expected_values, extracted_fields) — same formats used everywhere
    else in the pipeline, so comparator.py works without any changes.
    """
    _load_model()

    # Left panel — system/CRM expected values
    raw_system    = _call_model(image, SYSTEM_PANEL_PROMPT)
    parsed_system = _parse_json(raw_system)
    expected      = {k: None for k in FIELDS}
    if parsed_system:
        for key in FIELDS:
            expected[key] = _clean(parsed_system.get(key))

    # Right panel — actual loan document fields
    raw_doc    = _call_model(image, DOC_PANEL_PROMPT)
    parsed_doc = _parse_json(raw_doc)
    extracted  = _empty_fields()
    if parsed_doc and parsed_doc.get("document_type") != "invalid":
        fields = parsed_doc.get("fields", parsed_doc)
        for key in _ALL_KEYS:
            extracted[key] = _clean(fields.get(key))

    return expected, extracted
