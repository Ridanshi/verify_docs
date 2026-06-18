"""
Smoke test — run this BEFORE launching app.py.
Verifies: image load, model inference, field extraction, comparison.
No Gradio needed.
"""
import sys
import urllib.request
from pathlib import Path

# Download a FUNSD sample image if not present
TEST_IMAGE_URL = (
    "https://huggingface.co/datasets/nielsr/funsd/resolve/main/"
    "data/testing_data/images/82092117.png"
)
TEST_IMAGE_PATH = Path("test_doc.png")

if not TEST_IMAGE_PATH.exists():
    print("Downloading test image...")
    urllib.request.urlretrieve(TEST_IMAGE_URL, TEST_IMAGE_PATH)
    print(f"Saved -> {TEST_IMAGE_PATH}")

# Step 1: preprocess
print("\n[1/3] Loading image...")
from preprocessor import load_image
image = load_image(str(TEST_IMAGE_PATH))
print(f"      Image size: {image.size}, mode: {image.mode}")

# Step 2: extract (model downloads ~15 GB on first run, takes 5-10 min)
print("\n[2/3] Extracting fields (model loads now — first run takes ~5-10 min)...")
from extractor import extract_fields
extracted = extract_fields(image)
print("      Extracted fields:")
for k, v in extracted.items():
    print(f"        {k}: {v}")

# Step 3: compare against dummy expected values
print("\n[3/3] Running comparison...")
from comparator import compare_fields
expected = {
    "customer_name": "Test Customer",
    "bank_name": "Test Bank",
    "loan_account_number": "LOAN123456",
    "application_id": "APP001",
    "sanction_amount": "5000000",
    "disbursement_amount": "5000000",
    "loan_type": "Home Loan",
    "branch": "Main Branch",
    "disbursement_date": "2026-01-01",
}
result = compare_fields(extracted, expected)
print(f"      Status  : {result.status}")
print(f"      Comments: {result.comments or 'none'}")

print("\nSmoke test complete. Pipeline is working.")
print("Run: python app.py")
