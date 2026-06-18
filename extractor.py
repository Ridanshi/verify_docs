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

# Set USE_4BIT=1 on Kaggle/Colab (T4/P100, 16GB VRAM). Leave unset on RTX 4090+.
_USE_4BIT = os.environ.get("USE_4BIT", "0") == "1"


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


PROMPT = """You are a financial document extraction assistant.

Step 1: Identify the document type — one of:
  sanctioned_letter, disbursement_letter, offer_letter, banker_confirmation, invalid

If this image is not a financial document (photo of objects, people, or unrelated content),
set document_type to "invalid" and all fields to null.

Step 2: Extract these fields (set null if not found in the document):
  customer_name, bank_name, loan_account_number, application_id,
  sanction_amount, disbursement_amount, loan_type, branch, disbursement_date

Return ONLY valid JSON with no explanation:
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
