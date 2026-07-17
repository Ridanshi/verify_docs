"""
Scores the field-swap stress batch (synthetic/generate_field_swap_stress.py)
— isolates whether the model still occasionally puts the wrong value in the
wrong field (the "Mahindra Finance" ended up in customer_name bug from
earlier), across all 3 lender templates.

Every document is genuinely clean (expected_status is always APPROVED).
Beyond plain field-match accuracy, this script specifically detects the
SWAPPED pattern: extracted customer_name matching the expected BANK name
instead of the expected customer name (and the equivalent for
application_id <-> loan_account_number) — that's the exact failure mode
being checked for, distinct from a generic wrong-value error.

Usage:
    python eval_field_swap_stress.py
Produces:
    field_swap_stress_results.json
"""

import json
import time
from pathlib import Path

GROUND_TRUTH = Path("synthetic/field_swap_stress_ground_truth.json")
DOC_DIR      = Path("synthetic/data/field_swap_stress")
OUT_PATH     = "field_swap_stress_results.json"


def _norm(v):
    return (str(v).strip().lower()) if v else ""


def main():
    from preprocessor import load_image
    from extractor import extract_fields
    from comparator import compare_fields

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    entries = list(gt.items())
    total = len(entries)

    print(f"Evaluating {total} field-swap-stress documents...\n")

    correct = 0
    swapped_name_bank = 0
    swapped_id_lan = 0
    other_wrong = 0
    per_doc = []

    for i, (filename, entry) in enumerate(entries, 1):
        path = DOC_DIR / filename
        expected = entry["expected_values"]

        t0 = time.time()
        try:
            image = load_image(str(path))
            extracted = extract_fields(image)
            result = compare_fields(extracted, expected)
        except Exception as e:
            print(f"  [{i}/{total}] ERROR {filename}: {e}")
            per_doc.append({"file": filename, "error": str(e)})
            continue
        elapsed = time.time() - t0

        got_name = extracted.get("customer_name")
        got_bank = extracted.get("bank_name")
        got_app_id = extracted.get("application_id")
        got_lan = extracted.get("loan_account_number")

        # Detect the exact swap patterns seen before
        name_swapped_with_bank = (
            _norm(got_name) != _norm(expected["customer_name"])
            and _norm(got_name) == _norm(expected["bank_name"])
        )
        id_swapped_with_lan = (
            _norm(got_app_id) != _norm(expected["application_id"])
            and _norm(got_app_id) == _norm(expected["loan_account_number"])
        )

        if name_swapped_with_bank:
            swapped_name_bank += 1
            mark = "SWAPPED(name<->bank)"
        elif id_swapped_with_lan:
            swapped_id_lan += 1
            mark = "SWAPPED(app_id<->lan)"
        elif result.status == "APPROVED":
            correct += 1
            mark = "OK"
        else:
            other_wrong += 1
            mark = f"WRONG({result.status})"

        print(f"  [{i}/{total}] {mark}  {filename}  ({elapsed:.1f}s)  "
              f"expected_name='{expected['customer_name']}'  got_name='{got_name}'  "
              f"expected_bank='{expected['bank_name']}'  got_bank='{got_bank}'")

        per_doc.append({
            "file": filename,
            "lender": entry["lender"],
            "got_status": result.status,
            "expected_customer_name": expected["customer_name"],
            "extracted_customer_name": got_name,
            "expected_bank_name": expected["bank_name"],
            "extracted_bank_name": got_bank,
            "expected_application_id": expected["application_id"],
            "extracted_application_id": got_app_id,
            "expected_loan_account_number": expected["loan_account_number"],
            "extracted_loan_account_number": got_lan,
            "name_swapped_with_bank": name_swapped_with_bank,
            "id_swapped_with_lan": id_swapped_with_lan,
            "comments": result.comments,
            "elapsed_s": round(elapsed, 2),
        })

    print("\n" + "=" * 60)
    print("FIELD-SWAP-STRESS SUMMARY")
    print("=" * 60)
    print(f"  Correctly APPROVED (no swap)   : {correct}/{total}  ({100*correct/total:.1f}%)")
    print(f"  SWAPPED customer_name<->bank   : {swapped_name_bank}/{total}  <-- the bug being measured")
    print(f"  SWAPPED application_id<->LAN   : {swapped_id_lan}/{total}")
    print(f"  Other wrong verdict            : {other_wrong}/{total}")

    summary = {
        "total": total,
        "correct": correct,
        "swapped_name_bank": swapped_name_bank,
        "swapped_id_lan": swapped_id_lan,
        "other_wrong": other_wrong,
        "per_doc": per_doc,
    }
    Path(OUT_PATH).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Full results saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
