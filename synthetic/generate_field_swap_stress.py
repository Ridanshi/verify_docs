"""
Generates a small batch across all 3 lender templates to test the OTHER real
bug found this session: the model reading "Mahindra Finance" (the bank name)
into the customer_name field instead of the actual customer's name — a field
mislabeling error, not a digit-drop error, so the amount-refinement pass
doesn't touch it at all.

Every document here is genuinely clean (expected_status is always APPROVED,
no induced mismatch) — the only thing being measured is whether the model
assigns each value to the CORRECT field, especially the two pairs seen
swapped before: customer_name <-> bank_name, and application_id <->
loan_account_number.

Usage:
    python synthetic/generate_field_swap_stress.py
Produces:
    synthetic/data/field_swap_stress/*.pdf   (15 documents: 5 per lender)
    synthetic/field_swap_stress_ground_truth.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from synthetic.generate import (
    _mahindra_data, build_mahindra_pdf,
    _aadhar_data,   build_aadhar_pdf,
    _hdfc_data,     build_hdfc_pdf,
)

OUT_DIR = Path("synthetic/data/field_swap_stress")
GT_PATH = Path("synthetic/field_swap_stress_ground_truth.json")

LENDERS = [
    ("mahindra", _mahindra_data, build_mahindra_pdf),
    ("aadhar",   _aadhar_data,   build_aadhar_pdf),
    ("hdfc",     _hdfc_data,     build_hdfc_pdf),
]

DOCS_PER_LENDER = 5


def build_one(lender_name: str, data_fn, build_fn, idx: int) -> dict:
    fields = data_fn(idx=idx)  # unmodified — no induced mismatch, no amount tampering

    filename = f"field_swap_{lender_name}_{idx:03d}.pdf"
    build_fn(OUT_DIR / filename, fields)

    return {
        "file": filename,
        "lender": lender_name,
        "expected_values": {
            "customer_name":       fields["customer_name"],
            "bank_name":           fields["bank_name"],
            "loan_account_number": fields["loan_account_number"],
            "application_id":      fields["application_id"],
            "loan_type":           fields["loan_type"],
            "branch":              fields["branch"],
            "disbursement_date":   fields["disbursement_date_iso"],
        },
        "expected_status": "APPROVED",
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ground_truth = {}

    for lender_name, data_fn, build_fn in LENDERS:
        for i in range(1, DOCS_PER_LENDER + 1):
            entry = build_one(lender_name, data_fn, build_fn, idx=7000 + i)
            ground_truth[entry["file"]] = entry
            print(f"  Built {entry['file']}  "
                  f"(customer='{entry['expected_values']['customer_name']}', "
                  f"bank='{entry['expected_values']['bank_name']}')")

    GT_PATH.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nBuilt {len(ground_truth)} documents in {OUT_DIR}/")
    print(f"Ground truth written to {GT_PATH}")


if __name__ == "__main__":
    main()
