import json
import os
import re
import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from config import VLM_MODEL_ID, VLM_MAX_NEW_TOKENS, FIELDS

_model = None
_processor = None

# 32B model always needs 4-bit. 7B can run float16 on RTX 4090+.
_USE_4BIT = os.environ.get("USE_4BIT", "1") == "1"


def _load_model():
    global _model, _processor
    if _model is None:
        if _USE_4BIT:
            bnb_config = BitsAndBytesConfig(load_in_4bit=True)
            _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                VLM_MODEL_ID,
                quantization_config=bnb_config,
                device_map="auto",
            )
        else:
            _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                VLM_MODEL_ID,
                torch_dtype=torch.float16,
                device_map="auto",
            )
        _processor = AutoProcessor.from_pretrained(VLM_MODEL_ID)


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

  sanction_amount     — The total loan amount sanctioned/approved. Always express as
                        "X.XX lakhs" in Indian rupees. Examples:
                          ₹25,00,000  →  "25.00 lakhs"
                          Rs.25.00 lakhs  →  "25.00 lakhs"
                          ₹2,00,00,000  →  "200.00 lakhs"
                          Rs. 1,50,00,000/-  →  "150.00 lakhs"
                        Convert any format (crore, comma-separated, symbols) to lakhs.

  disbursement_amount — The amount actually disbursed. Always express as "X.XX lakhs"
                        using the same conversion rules as sanction_amount.
                        May differ from sanction_amount.

  loan_type           — Category of loan, e.g. "Home Loan", "SME Loan", "Mortgage Loan",
                        "Loan Against Property". Extract as written.

  branch              — The branch name or city where the loan is being processed.
                        Usually labelled "Branch", "Branch Office", or "Processing Centre".

  disbursement_date   — The date of disbursement as written in the document
                        (e.g. "19 Jun 2026", "19.06.2026"). NOT the sanction date.

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
    "disbursement_amount": "...",
    "loan_type": "...",
    "branch": "...",
    "disbursement_date": "..."
  }
}"""

STRICT_PROMPT = PROMPT + "\n\nIMPORTANT: Return ONLY the JSON object. No text before or after."


def _call_model(image: Image.Image, prompt: str) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = _processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(_model.device)

    with torch.no_grad():
        generated_ids = _model.generate(**inputs, max_new_tokens=VLM_MAX_NEW_TOKENS)

    input_len = inputs["input_ids"].shape[1]
    new_tokens = generated_ids[:, input_len:]
    return _processor.batch_decode(new_tokens, skip_special_tokens=True)[0]


def _parse_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _empty_fields() -> dict:
    return {f: None for f in FIELDS}


def extract_fields(image: Image.Image) -> dict:
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
    for key in FIELDS:
        val = fields.get(key)
        result[key] = str(val).strip() if val and str(val).strip().lower() != "null" else None

    return result
