"""
Batch evaluation of the DB Verify pipeline against synthetic/ground_truth.json.

Mirrors eval.py but routes the expected values through PostgreSQL instead of
reading them directly from ground_truth.json. Confirms end-to-end that:
  filename (LAN) → DB lookup → VLM extract → compare → verdict
matches the ground-truth expected status.

Prereq:
  python seed_db_eval.py   # seed DB from ground_truth.json (once per session)

Usage:
  python eval_db.py                  # all 150 docs
  python eval_db.py --limit 10       # quick sanity check
  python eval_db.py --pdfs-only      # 75 PDFs only
  python eval_db.py --lender aadhar  # filter by lender prefix
  python eval_db.py --out results_db.json
"""
import argparse
import json
import time
from pathlib import Path

GROUND_TRUTH = Path("synthetic/ground_truth.json")
PDF_DIR      = Path("synthetic/data/pdfs")
IMG_DIR      = Path("synthetic/data/images")


def resolve_path(filename: str) -> Path | None:
    p = (PDF_DIR if filename.endswith(".pdf") else IMG_DIR) / filename
    return p if p.exists() else None


def db_record_to_expected(db_record):
    """Same logic as app.db_verify — translate DB row into the dict the comparator expects."""
    disb_date = db_record.get("disbursement_date")
    return {
        "customer_name":       db_record.get("customer_name"),
        "bank_name":           db_record.get("bank_name"),
        "loan_account_number": db_record.get("loan_account_number"),
        "application_id":      db_record.get("application_id"),
        "sanction_amount":     str(int(db_record["sanction_amount"]))     if db_record.get("sanction_amount")     else None,
        "disbursement_amount": str(int(db_record["disbursement_amount"])) if db_record.get("disbursement_amount") else None,
        "loan_type":           db_record.get("loan_type"),
        "branch":              db_record.get("branch"),
        "disbursement_date":   disb_date.isoformat() if disb_date else None,
    }


def run_eval(limit, pdfs_only, out_path, lender):
    from preprocessor import load_image
    from extractor   import extract_fields
    from comparator  import compare_fields
    from db_lookup   import lookup_by_lan, LookupError, AmbiguousRecordError, DBConnectionError

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    entries = list(gt.items())
    if pdfs_only:
        entries = [(k, v) for k, v in entries if k.endswith(".pdf")]
    if lender:
        entries = [(k, v) for k, v in entries if k.startswith(lender)]
    if limit:
        entries = entries[:limit]

    total = len(entries)
    print(f"Evaluating {total} documents through DB Verify pipeline...\n")

    status_correct     = 0
    needs_review_count = 0
    db_lookup_failures = 0
    confusion          = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
    per_doc            = []
    skipped            = 0

    for i, (filename, entry) in enumerate(entries, 1):
        path = resolve_path(filename)
        if path is None:
            print(f"  [{i}/{total}] SKIP  {filename}  (file not found)")
            skipped += 1
            continue

        lan             = entry["expected_values"]["loan_account_number"]
        expected_status = entry["expected_status"]

        t0 = time.time()

        # Step 1: lookup DB by LAN (the filename in real workflow).
        try:
            db_record = lookup_by_lan(lan)
        except (LookupError, AmbiguousRecordError) as e:
            print(f"  [{i}/{total}] DBMISS {filename}  ({lan})  {e}")
            db_lookup_failures += 1
            per_doc.append({"file": filename, "lan": lan, "error": f"DB lookup: {e}"})
            continue
        except DBConnectionError as e:
            print(f"FATAL: DB unreachable — {e}")
            return

        expected = db_record_to_expected(db_record)

        # Step 2: VLM extract from doc.
        try:
            image     = load_image(str(path))
            extracted = extract_fields(image)
            result    = compare_fields(extracted, expected)
        except Exception as e:
            print(f"  [{i}/{total}] ERROR {filename}: {e}")
            per_doc.append({"file": filename, "error": str(e)})
            skipped += 1
            continue

        elapsed   = time.time() - t0
        got       = result.status
        status_ok = (got == expected_status)
        if got == "NEEDS_REVIEW":
            needs_review_count += 1
        if status_ok:
            status_correct += 1

        if expected_status == "CHANGES_REQUESTED" and got == "CHANGES_REQUESTED":
            confusion["TP"] += 1
        elif expected_status == "APPROVED" and got == "APPROVED":
            confusion["TN"] += 1
        elif expected_status == "APPROVED" and got == "CHANGES_REQUESTED":
            confusion["FP"] += 1
        else:
            confusion["FN"] += 1

        mark = "OK" if status_ok else "FAIL"
        print(f"  [{i}/{total}] {mark}  {filename}  ({elapsed:.1f}s)  status={got}  expected={expected_status}")

        per_doc.append({
            "file":            filename,
            "lan":             lan,
            "expected_status": expected_status,
            "got_status":      got,
            "status_correct":  status_ok,
            "comments":        result.comments,
            "elapsed_s":       round(elapsed, 2),
        })

    # ── Summary ─────────────────────────────────────────────────────────────
    evaluated = total - skipped - db_lookup_failures
    print("\n" + "=" * 60)
    print("DB VERIFY EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Documents evaluated : {evaluated} / {total}  ({skipped} skipped, {db_lookup_failures} DB miss)")

    if evaluated == 0:
        print("  No documents evaluated.")
        return

    status_pct = 100 * status_correct / evaluated
    print(f"  Status accuracy     : {status_correct}/{evaluated}  ({status_pct:.1f}%)")
    print(f"  Needs review        : {needs_review_count}/{evaluated}  ({100*needs_review_count/evaluated:.1f}%)")

    prec = confusion["TP"] / (confusion["TP"] + confusion["FP"]) if (confusion["TP"] + confusion["FP"]) else 0
    rec  = confusion["TP"] / (confusion["TP"] + confusion["FN"]) if (confusion["TP"] + confusion["FN"]) else 0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    print(f"  Precision (CR)      : {prec:.3f}")
    print(f"  Recall    (CR)      : {rec:.3f}")
    print(f"  F1        (CR)      : {f1:.3f}")
    print(f"  Confusion           : TP={confusion['TP']} TN={confusion['TN']} "
          f"FP={confusion['FP']} FN={confusion['FN']}")

    summary = {
        "total": total,
        "evaluated": evaluated,
        "skipped": skipped,
        "db_lookup_failures": db_lookup_failures,
        "status_accuracy": round(status_pct, 2),
        "precision_cr": round(prec, 4),
        "recall_cr": round(rec, 4),
        "f1_cr": round(f1, 4),
        "confusion": confusion,
        "per_doc": per_doc,
    }
    Path(out_path).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Full results saved -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",     type=int, default=None)
    ap.add_argument("--pdfs-only", action="store_true")
    ap.add_argument("--lender",    type=str, default=None, help="aadhar | mahindra | hdfc")
    ap.add_argument("--out",       default="eval_db_results.json")
    args = ap.parse_args()
    run_eval(args.limit, args.pdfs_only, args.out, args.lender)
