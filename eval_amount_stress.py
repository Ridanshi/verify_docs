"""
Scores the amount-stress batch (synthetic/generate_amount_stress.py) — isolates
one question: does the model read digit-only amounts (no words backup)
correctly across a spread of magnitudes, or does it drop a factor of
10/100/1000?

Every document in this batch is genuinely correct (expected_status is always
APPROVED). This script reports it differently from eval.py's generic status
accuracy: it specifically calls out FALSE_NEEDS_REVIEW as its own category,
since that's the exact failure mode being measured — a fine document wrongly
sent for manual review because the digits were misread and there were no
words to reconcile against.

Usage:
    python eval_amount_stress.py
Produces:
    amount_stress_results.json
"""

import json
import time
from pathlib import Path

GROUND_TRUTH = Path("synthetic/amount_stress_ground_truth.json")
DOC_DIR      = Path("synthetic/data/amount_stress")
OUT_PATH     = "amount_stress_results.json"


def main():
    from preprocessor import load_image
    from extractor import extract_fields
    from comparator import compare_fields

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    entries = list(gt.items())
    total = len(entries)

    print(f"Evaluating {total} amount-stress documents...\n")

    correct = 0
    false_needs_review = 0
    other_wrong = 0
    per_doc = []

    for i, (filename, entry) in enumerate(entries, 1):
        path = DOC_DIR / filename
        expected = entry["expected_values"]
        true_rupees = entry["true_rupees"]

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

        got_sanction = extracted.get("sanction_amount")
        got_disb     = extracted.get("disbursement_amount")

        if result.status == "APPROVED":
            correct += 1
            mark = "OK"
        elif result.status == "NEEDS_REVIEW":
            false_needs_review += 1
            mark = "FALSE_NEEDS_REVIEW"
        else:
            other_wrong += 1
            mark = f"WRONG({result.status})"

        print(f"  [{i}/{total}] {mark}  {filename}  ({elapsed:.1f}s)  "
              f"true=Rs.{true_rupees:,}  extracted_sanction='{got_sanction}'  extracted_disb='{got_disb}'")

        per_doc.append({
            "file": filename,
            "true_rupees": true_rupees,
            "got_status": result.status,
            "extracted_sanction_amount": got_sanction,
            "extracted_disbursement_amount": got_disb,
            "comments": result.comments,
            "elapsed_s": round(elapsed, 2),
        })

    print("\n" + "=" * 60)
    print("AMOUNT-STRESS SUMMARY")
    print("=" * 60)
    print(f"  Correctly APPROVED       : {correct}/{total}  ({100*correct/total:.1f}%)")
    print(f"  FALSE NEEDS_REVIEW       : {false_needs_review}/{total}  ({100*false_needs_review/total:.1f}%)  <-- the failure mode being measured")
    print(f"  Other wrong verdict      : {other_wrong}/{total}")

    summary = {
        "total": total,
        "correct": correct,
        "false_needs_review": false_needs_review,
        "other_wrong": other_wrong,
        "per_doc": per_doc,
    }
    Path(OUT_PATH).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Full results saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
