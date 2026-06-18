"""
Batch evaluation against synthetic/ground_truth.json.

Usage:
    python eval.py                  # all 150 docs
    python eval.py --limit 10       # first N docs (quick sanity check)
    python eval.py --pdfs-only      # skip JPGs (75 docs)
    python eval.py --out results.json

Reports:
    - Status accuracy  (APPROVED / CHANGES_REQUESTED correct?)
    - Per-field extraction accuracy  (did VLM pull the right raw value?)
    - Confusion matrix
    - Saves per-doc detail to --out file
"""
import argparse
import json
import time
from pathlib import Path

GROUND_TRUTH = Path("synthetic/ground_truth.json")
PDF_DIR      = Path("synthetic/data/pdfs")
IMG_DIR      = Path("synthetic/data/images")


def resolve_path(filename: str) -> Path | None:
    if filename.endswith(".pdf"):
        p = PDF_DIR / filename
    else:
        p = IMG_DIR / filename
    return p if p.exists() else None


def run_eval(limit: int | None, pdfs_only: bool, out_path: str) -> None:
    from preprocessor import load_image
    from extractor import extract_fields
    from comparator import compare_fields

    gt: dict = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    entries = list(gt.items())
    if pdfs_only:
        entries = [(k, v) for k, v in entries if k.endswith(".pdf")]
    if limit:
        entries = entries[:limit]

    total = len(entries)
    print(f"Evaluating {total} documents...\n")

    # accumulators
    status_correct = 0
    field_hits: dict[str, int]   = {}
    field_total: dict[str, int]  = {}
    confusion = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}   # pos = CHANGES_REQUESTED
    per_doc: list[dict] = []
    skipped = 0

    for i, (filename, entry) in enumerate(entries, 1):
        path = resolve_path(filename)
        if path is None:
            print(f"  [{i}/{total}] SKIP  {filename}  (file not found)")
            skipped += 1
            continue

        expected_values = entry["expected_values"]
        expected_status = entry["expected_status"]
        raw_fields      = entry["document_raw_fields"]

        t0 = time.time()
        try:
            image    = load_image(str(path))
            extracted = extract_fields(image)
            result   = compare_fields(extracted, expected_values)
        except Exception as e:
            print(f"  [{i}/{total}] ERROR {filename}: {e}")
            per_doc.append({"file": filename, "error": str(e)})
            skipped += 1
            continue

        elapsed = time.time() - t0
        got_status = result.status
        status_ok  = got_status == expected_status

        if status_ok:
            status_correct += 1
        # confusion matrix (positive class = CHANGES_REQUESTED)
        if expected_status == "CHANGES_REQUESTED" and got_status == "CHANGES_REQUESTED":
            confusion["TP"] += 1
        elif expected_status == "APPROVED" and got_status == "APPROVED":
            confusion["TN"] += 1
        elif expected_status == "APPROVED" and got_status == "CHANGES_REQUESTED":
            confusion["FP"] += 1
        else:
            confusion["FN"] += 1

        # per-field accuracy: does the pipeline match extracted vs normalized expected?
        from comparator import _fields_match
        from config import FIELDS
        field_detail: dict[str, dict] = {}
        for field in FIELDS:
            expected_val = expected_values.get(field)
            if not expected_val:
                continue
            field_total[field] = field_total.get(field, 0) + 1
            got_raw = (extracted or {}).get(field)
            hit = _fields_match(field, got_raw, expected_val)
            if hit:
                field_hits[field] = field_hits.get(field, 0) + 1
            field_detail[field] = {"expected": expected_val, "got": got_raw, "match": hit}

        mark = "OK" if status_ok else "FAIL"
        print(f"  [{i}/{total}] {mark}  {filename}  ({elapsed:.1f}s)  "
              f"status={got_status}  expected={expected_status}")

        per_doc.append({
            "file":            filename,
            "expected_status": expected_status,
            "got_status":      got_status,
            "status_correct":  status_ok,
            "comments":        result.comments,
            "fields":          field_detail,
            "elapsed_s":       round(elapsed, 2),
        })

    # ── Summary ──────────────────────────────────────────────────────────────
    evaluated = total - skipped
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Documents evaluated : {evaluated} / {total}  ({skipped} skipped)")

    if evaluated == 0:
        print("  No documents evaluated.")
        return

    status_pct = 100 * status_correct / evaluated
    print(f"  Status accuracy     : {status_correct}/{evaluated}  ({status_pct:.1f}%)")

    prec = confusion["TP"] / (confusion["TP"] + confusion["FP"]) if (confusion["TP"] + confusion["FP"]) else 0
    rec  = confusion["TP"] / (confusion["TP"] + confusion["FN"]) if (confusion["TP"] + confusion["FN"]) else 0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    print(f"  Precision (CR)      : {prec:.3f}")
    print(f"  Recall    (CR)      : {rec:.3f}")
    print(f"  F1        (CR)      : {f1:.3f}")
    print(f"  Confusion           : TP={confusion['TP']} TN={confusion['TN']} "
          f"FP={confusion['FP']} FN={confusion['FN']}")

    print("\n  Per-field extraction accuracy:")
    all_hits = 0
    all_total = 0
    for field in sorted(field_total):
        hits  = field_hits.get(field, 0)
        denom = field_total[field]
        pct   = 100 * hits / denom
        all_hits  += hits
        all_total += denom
        print(f"    {field:<30} {hits:>3}/{denom:<3}  {pct:5.1f}%")
    if all_total:
        print(f"    {'OVERALL':<30} {all_hits:>3}/{all_total:<3}  {100*all_hits/all_total:5.1f}%")

    # ── Save detail ──────────────────────────────────────────────────────────
    summary = {
        "total": total,
        "evaluated": evaluated,
        "skipped": skipped,
        "status_accuracy": round(status_pct, 2),
        "precision_cr": round(prec, 4),
        "recall_cr": round(rec, 4),
        "f1_cr": round(f1, 4),
        "confusion": confusion,
        "per_field_accuracy": {
            f: round(100 * field_hits.get(f, 0) / field_total[f], 2)
            for f in field_total
        },
        "per_doc": per_doc,
    }
    Path(out_path).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Full results saved -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",     type=int, default=None, help="Evaluate first N docs only")
    ap.add_argument("--pdfs-only", action="store_true",    help="Skip JPGs")
    ap.add_argument("--out",       default="eval_results.json", help="Output JSON path")
    args = ap.parse_args()
    run_eval(args.limit, args.pdfs_only, args.out)
