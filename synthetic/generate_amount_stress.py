"""
Generates a small batch of documents that isolate ONE question: does the model
correctly read digit-only amounts (no words-in-brackets backup) across a
spread of magnitudes, or does it drop a factor of 10/100/1000 like before?

Every document here is genuinely correct (expected_status is always APPROVED)
— there's no induced mismatch. This is deliberately different from
synthetic/generate.py's ground_truth.json, which has zero digit-only-amount
cases and no NEEDS_REVIEW-labeled documents at all (confirmed by inspection).

A false NEEDS_REVIEW here (document IS approvable, but got flagged for review)
means: digit-drop is still happening. A correct APPROVED here means: the
32B model + amount-refinement pass fixed the digit-drop for this case.

Usage:
    python synthetic/generate_amount_stress.py
Produces:
    synthetic/data/amount_stress/*.pdf   (10 documents)
    synthetic/amount_stress_ground_truth.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from synthetic.generate import _mahindra_data, build_mahindra_pdf, indian_comma

OUT_DIR = Path("synthetic/data/amount_stress")
GT_PATH = Path("synthetic/amount_stress_ground_truth.json")

# Spread of lakh values chosen to stress different digit-drop points:
# short (5-6 digit), medium (7 digit), long (8-9 digit / crore-range).
# A dropped zero shows up differently depending on where in the number it sits.
TEST_LAKHS = [5.0, 12.0, 25.0, 40.0, 63.5, 78.25, 99.99, 150.0, 250.0, 500.0]


def build_one(idx: int, lakhs: float) -> dict:
    fields = _mahindra_data(idx=idx)
    rupees = int(lakhs * 100_000)

    # Digits only — no bracketed words at all. This removes the safety net
    # that normally lets the comparator recover a dropped digit.
    digits_only = f"Rs.{indian_comma(rupees)}.00"
    fields["sanction_amount"]     = digits_only
    fields["disbursement_amount"] = digits_only

    filename = f"amount_stress_{idx:03d}.pdf"
    build_mahindra_pdf(OUT_DIR / filename, fields)

    return {
        "file": filename,
        "expected_values": {
            "customer_name":       fields["customer_name"],
            "bank_name":           fields["bank_name"],
            "loan_account_number": fields["loan_account_number"],
            "application_id":      fields["application_id"],
            "sanction_amount":     rupees,
            "disbursement_amount": rupees,
            "loan_type":           fields["loan_type"],
            "branch":              fields["branch"],
            "disbursement_date":   fields["disbursement_date_iso"],
        },
        "expected_status": "APPROVED",  # every doc here is genuinely correct
        "true_rupees": rupees,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ground_truth = {}

    for i, lakhs in enumerate(TEST_LAKHS, start=1):
        entry = build_one(i, lakhs)
        ground_truth[entry["file"]] = entry
        print(f"  Built {entry['file']}  (true amount: Rs.{entry['true_rupees']:,})")

    GT_PATH.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nBuilt {len(TEST_LAKHS)} documents in {OUT_DIR}/")
    print(f"Ground truth written to {GT_PATH}")


if __name__ == "__main__":
    main()
