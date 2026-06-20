import json
import os
import re
import torch
from PIL import Image # PIL image object passed into the VLM.
# Qwen VL model + processor.
# BitsAndBytes enables 4-bit quantization to fit the 32B model into T4 GPUs.
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info # Helper from Qwen for preparing image/video inputs.
from config import VLM_MODEL_ID, VLM_MAX_NEW_TOKENS, FIELDS, AMOUNT_WORD_FIELDS

_model = None # No model loaded yet
_processor = None # No processor loaded yet

# 32B model always needs 4-bit. 7B can run float16 on RTX 4090+.
_USE_4BIT = os.environ.get("USE_4BIT", "1") == "1"


def _load_model():
    global _model, _processor
    if _model is None:
        num_gpus = torch.cuda.device_count() # Determine how many CUDA GPUs are available
        if num_gpus == 0:
            raise RuntimeError(
                "No CUDA GPU detected. This model requires a GPU with ≥8GB VRAM. "
                "Run on Kaggle T4 x2 or a cloud GPU instance."
            )
        # Reserve up to 13GB on each GPU.
        # On Kaggle T4 x2 this distributes the model across both GPUs.
        max_memory = {i: "13GiB" for i in range(num_gpus)}
        max_memory["cpu"] = "0GiB"

        try:
            if _USE_4BIT:
                bnb_config = BitsAndBytesConfig(load_in_4bit=True) # Load the model using 4-bit quantization to reduce VRAM usage
                _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    VLM_MODEL_ID,
                    quantization_config=bnb_config,
                    device_map="auto",
                    max_memory=max_memory,
                )
            else:
                _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    VLM_MODEL_ID,
                    torch_dtype=torch.float16,
                    device_map="auto",
                    max_memory=max_memory,
                )
            _processor = AutoProcessor.from_pretrained(VLM_MODEL_ID)
        except Exception:
            _model = None
            _processor = None
            torch.cuda.empty_cache()
            raise


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
                        "Loan Account No", "Account Number", or "LAP No". It is a unique
                        identifier for the loan itself, different from the application ID.
                        Copy EVERY character exactly — do not skip, add, or transpose digits.

  application_id      — The loan application reference number. Usually labelled
                        "Application No", "Application ID", or "Ref No". It identifies
                        the application, not the loan account.
                        Copy EVERY character exactly — do not skip, add, or transpose digits.

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

STRICT_PROMPT = PROMPT + "\n\nIMPORTANT: Return ONLY the JSON object. No text before or after."


def _call_model(image: Image.Image, prompt: str) -> str:
    # Build a multimodal chat message containing: - the document image - the extraction promp
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    
    # Convert the message into Qwen's internal chat format.
    # add_generation_prompt=True tells the model that it should generate a response after the provided message.
    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    
    # Extract image/video inputs in the format expected by Qwen
    image_inputs, video_inputs = process_vision_info(messages)
    
    # Convert text + image into PyTorch tensors and move them onto the same device(s) as the model.
    inputs = _processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(_model.device)

    with torch.no_grad():
        generated_ids = _model.generate(**inputs, max_new_tokens=VLM_MAX_NEW_TOKENS) # Generate model output

    input_len = inputs["input_ids"].shape[1]
    new_tokens = generated_ids[:, input_len:]
    
    # Convert generated token IDs back into readable text.
    return _processor.batch_decode(new_tokens, skip_special_tokens=True)[0]

# Extract and parse JSON from model output
def _parse_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group()) # Convert JSON string into a Python dictionary
    except json.JSONDecodeError:
        return None

# All keys the model is asked to return: the 9 standard fields plus the
# amount-in-words companions used for digit cross-checking.
_ALL_KEYS = FIELDS + list(AMOUNT_WORD_FIELDS.values())


# Used whenever extraction fails or the document is invalid
def _empty_fields() -> dict:
    return {k: None for k in _ALL_KEYS}


def _clean(val) -> str | None:
    return str(val).strip() if val and str(val).strip().lower() != "null" else None


def extract_fields(image: Image.Image) -> dict:
    """Extract all fields (digits + amount-in-words) from the document image.

    Retries once with a stricter prompt if the first JSON is unparseable.
    A successful retry is NOT treated as low-confidence — the words/digits
    cross-check in the comparator is what flags genuine amount uncertainty.
    """
    _load_model()

    raw = _call_model(image, PROMPT)
    parsed = _parse_json(raw)

    if parsed is None:
        raw = _call_model(image, STRICT_PROMPT)
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
