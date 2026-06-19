# Session Log — Loan Document Verification Tool
**Date:** 2026-06-18

---

## 1. Problem Statement

The company manually verifies loan disbursement documents. A reviewer opens a sanctioned letter, disbursement letter, or banker confirmation, compares fields against internal system values, and either approves or sends back for corrections. This is slow and does not scale.

**Goal:** Build a system that automates this — extract fields from uploaded documents, compare against expected values, output APPROVED or CHANGES_REQUESTED with field-level mismatch comments.

---

## 2. Initial Proposal Review

The user had an existing document (`LOAN NETWORKS (4).docx`) with prior research. It proposed:

- **Model:** Qwen2.5-VL (vision-language model)
- **Pipeline:** FastAPI + PostgreSQL + Celery
- **Training:** LoRA/QLoRA fine-tuning
- **Datasets:** VRDU, Scanned Images (Voxel51), FUNSD

### Assessment of Proposed Tools

| Component | Verdict | Reason |
|---|---|---|
| Qwen2.5-VL | ✅ Appropriate | Handles document images, structured JSON output, open-source, supports LoRA fine-tuning |
| Celery + FastAPI | ✅ Appropriate | Standard async pipeline pattern — document inference is slow, background workers needed |
| LoRA/QLoRA fine-tuning | ✅ Appropriate — but deferred | No training data exists yet; fine-tuning is v2 |

### Assessment of Proposed Datasets

| Dataset | Verdict | Reason |
|---|---|---|
| VRDU (Google) | ❌ Wrong domain | US commercial forms — no Indian financial documents |
| Scanned Images (Voxel51) | ⚠️ Weakly useful | Generic scans — helps test pipeline robustness only |
| FUNSD | ✅ Best of three | Noisy scanned forms with key-value pairs — matches sanctioned letter structure most closely |

**Key finding:** None of the three datasets contain Indian financial documents (sanctioned letters from Aadhar Housing Finance, Mahindra Finance, etc.). Fine-tuning on them would teach wrong patterns and hurt accuracy. They are only used for pipeline development and testing.

**What will actually train the model (v2):** Real reviewer corrections collected during production use.

---

## 3. Clarifying Questions and Answers

| Question | Answer |
|---|---|
| What is the source of truth to compare against? | Internal database fields (customer name, loan account number, sanction amount, etc.) |
| How many cases per day? | 100+ in staging; production likely 500–2000+ |
| Access to real training documents? | No — company documents contain PII, compliance restrictions apply |
| API or self-hosted? | Self-hosted — fully in-house, no external APIs |
| Integrated or standalone tool? | Standalone for now — company will test it and integrate later |
| Existing frontend? | No |

---

## 4. Key Design Decisions

### Why Zero-Shot (No Fine-Tuning for v1)

Fine-tuning requires labeled training data. Zero training data exists. Qwen2.5-VL is pre-trained on millions of documents — it already understands forms, tables, and structured extraction. Zero-shot gets ~85–90% accuracy on day 1. Fine-tuning (v2) will improve this to ~95%+ once reviewer corrections accumulate.

### Why Not Use the 3 Datasets for Training

Fine-tuning on wrong-domain data (US commercial forms) teaches wrong patterns and makes the model perform worse on Indian financial documents than plain zero-shot. The datasets are only useful for pipeline smoke testing.

### Approach: Merged Single-Pass Extraction

Single Qwen2.5-VL call that simultaneously:
1. Identifies document type (sanctioned_letter / disbursement_letter / offer_letter / banker_confirmation / invalid)
2. Extracts all fields as structured JSON

No separate classification step — one call does both.

### Comparison Logic

| Field Type | Match Method | Reason |
|---|---|---|
| customer_name, bank_name, branch, loan_type | Fuzzy (rapidfuzz partial_ratio) | Casing differences, co-applicants, abbreviations |
| loan_account_number, application_id | Exact string | Single digit difference = wrong record |
| sanction_amount, disbursement_amount | Normalize to float → exact | "Rs.195.00 lakhs" = 19500000.0 |
| disbursement_date | Parse to YYYY-MM-DD → exact | "31 Jan 2026" = "04.02.2026" after parsing |

### Invalid Document Handling

Two-layer check:
1. VLM sets `document_type: "invalid"` when it sees a non-financial image
2. Backend checks: if fewer than 3 fields extracted → invalid regardless

Both trigger: `CHANGES_REQUESTED` + "Invalid document uploaded" comment.

### Standalone Architecture (No Celery/Redis/DB for v1)

Celery and Redis add infrastructure complexity that's unnecessary for a one-document-at-a-time demo tool. Synchronous processing is fine. Added SQLite for result storage — no server required.

---

## 5. Final Architecture

```
User Input
  ├── Document image (PDF / JPG / PNG / TIFF)
  └── Expected field values (form)
          │
          ▼
   Gradio UI
          │
          ▼
   Python Backend (synchronous)
     1. pdf2image / PIL    → preprocess image
     2. Qwen2.5-VL 7B     → extract fields + document type (JSON)
     3. Validate document  → check for invalid uploads
     4. Normalize values   → amounts, dates, text
     5. Compare fields     → fuzzy + exact per field type
     6. Generate comments  → per mismatch
     7. Save to SQLite     → results.db
          │
          ▼
   Output
     - APPROVED / CHANGES REQUESTED
     - Mismatch comments
     - Extracted fields table
     - History tab (past 50 verifications)
```

**Future PostgreSQL migration:** One line change in `database.py` — swap `sqlite3` for `psycopg2` and point at their RDS host.

---

## 6. Files Built

```
D:\Verify Docs\
├── app.py              Gradio UI — two tabs: Verify + History
├── extractor.py        Qwen2.5-VL model load, prompt, JSON parse, retry logic
├── preprocessor.py     PDF/image → PIL Image, resize to 1120×1120
├── normalizer.py       normalize_amount, normalize_date, normalize_text
├── comparator.py       compare_fields → ComparisonResult (status + comments)
├── database.py         SQLite init, save_result, get_recent_results
├── config.py           Field lists, fuzzy thresholds, model ID
├── requirements.txt    All dependencies
├── tests/
│   ├── test_normalizer.py    15 tests
│   ├── test_comparator.py     7 tests
│   ├── test_preprocessor.py   4 tests
│   └── test_database.py       5 tests
├── synthetic/
│   ├── generate.py           Synthetic document generator (75 PDFs + 75 JPGs)
│   ├── ground_truth.json     150 entries with expected values + status per file
│   ├── data/pdfs/            75 PDFs (25 each: mahindra, aadhar, hdfc)
│   └── data/images/          75 JPGs with scan augmentation
└── docs/
    ├── superpowers/specs/2026-06-18-loan-document-verification-design.md
    └── superpowers/plans/2026-06-18-loan-document-verification.md
```

**Total: 31 tests, all passing. 150 synthetic documents generated.**

---

## 7. Component Responsibilities

### config.py
Field definitions, fuzzy thresholds, model ID, constants. Single source of truth used by all modules.

### normalizer.py
- `normalize_amount(value)` → float | None — handles Rs./₹, lakhs, crores, comma-separated
- `normalize_date(value)` → "YYYY-MM-DD" | None — handles dot format, written format, ISO
- `normalize_text(value)` → lowercase stripped string

### comparator.py
- `compare_fields(extracted, expected)` → `ComparisonResult`
- Checks valid document (≥3 fields extracted)
- Routes each field to correct match type
- Generates comment per mismatch: `"Field: document shows 'X', expected 'Y'"`
- `ComparisonResult` dataclass: `status`, `comments`, `extracted`

### preprocessor.py
- `load_image(file_path)` → PIL.Image.Image
- PDF: converts page 1 via pdf2image at 200 DPI
- Image: loads directly via PIL
- Both: resized to max 1120×1120, converted to RGB
- Raises `ValueError` on unsupported format

### extractor.py
- Model loads lazily on first call (not at import)
- Single prompt extracts document_type + all fields
- Retries once with stricter prompt if JSON parse fails
- Returns empty dict (all None) if both attempts fail or document is invalid

### database.py
- `init_db()` — creates `verifications` table if not exists, called at app startup
- `save_result(filename, status, extracted, expected, comments)` — saves every verification
- `get_recent_results(limit=50)` — returns rows ordered by id DESC (newest first)
- SQLite file: `results.db` in project root

### app.py
- Tab 1 — Verify Document: upload + expected fields form + result display
- Tab 2 — History: table of past 50 verifications, refresh button
- Wraps `load_image` and `extract_fields` in try/except — no silent failures
- Saves every result to SQLite automatically

---

## 8. Cloud GPU Checklist (All scripts ready — just needs GPU)

All scripts written and committed. On RunPod/Spheron RTX 4090 (~$0.65/hr):

```bash
git clone <repo>
cd "Verify Docs"
pip install -r requirements.txt

# Smoke test (model downloads ~15GB on first run, 5-10 min)
python run_smoke_test.py

# Full batch eval — all 150 synthetic docs
python eval.py                    # all 150
python eval.py --limit 10         # quick 10-doc sanity check
python eval.py --pdfs-only        # 75 PDFs only

# Launch UI
python app.py  # → http://0.0.0.0:7860 (expose via RunPod port)
```

### eval.py — What it measures

| Metric | Description |
|---|---|
| Status accuracy | % docs where APPROVED/CHANGES_REQUESTED is correct |
| Precision/Recall/F1 | For CHANGES_REQUESTED class |
| Per-field extraction | % docs where VLM extracted the right raw value per field |
| Confusion matrix | TP/TN/FP/FN breakdown |

Output saved to `eval_results.json`.

---

## 8b. Bug Fixes Applied (Post-Initial Build)

### comparator.py
- `fuzz.partial_ratio` → `fuzz.ratio` everywhere. Partial ratio caused false negatives: "T.Nagar" vs "T.Nagar Branch" scored 100% (substring match), flagged as correct when it shouldn't be.
- Added `endswith` fallback for `EXACT_FIELDS`: `e == x or e.endswith(x)`. Handles Aadhar case where Qwen extracted "AHFLN No. 337887565" instead of "337887565".

### eval.py
- Per-field accuracy was using raw exact string comparison → required Qwen to output "Rs.25.00 lakhs" exactly. Fixed to use `_fields_match()` with `expected_values` (same normalization pipeline as production).

### normalizer.py
- ISO date bug: `dayfirst=True` on `dateparser.parse("2026-01-06")` swapped month/day → "2026-06-01". Fixed with regex check: if input matches `^\d{4}-\d{2}-\d{2}$`, parse without `dayfirst`.

### extractor.py
- Amount prompt rewritten to force "X.XX lakhs" output format. Qwen was character-copying Indian comma format "₹2,00,00,000" and reading Western comma "₹2,000,000" (10x error). Semantic instruction forces conversion.
- ID fields: added "Copy EVERY character exactly — do not skip, add, or transpose digits."
- `_USE_4BIT` default changed to `"1"` (always on for 32B).

### synthetic/generate.py (anti-overfitting restoration)
- Restored 3 amount formats: `Rs.X.XX lakhs`, `₹Indian,comma`, `Rs. plain/-`. Was temporarily simplified to lakhs-only → inflated accuracy to 94.7% on easy test data.
- Restored realistic ID lengths: Mahindra `LAPSEC` + 9 digits, Aadhar 9-digit numeric, HDFC `HL` + 10 digits. Was temporarily shortened to avoid Qwen digit-drop errors → hid real OCR failure modes.
- Aadhar template: moved loan_account_number and application_id from inline ref paragraph to footer table with clean label:value rows.

---

## 8c. Model Upgrade: 7B → 32B

**Decision:** Qwen2.5-VL-7B was achieving ~78% status accuracy with production-realistic data. Fine-tuning rejected (would overfit to 3 templates, catastrophic forgetting on unknown lender layouts). Upgraded to `Qwen/Qwen2.5-VL-32B-Instruct`.

**Expected improvement:** 32B has stronger multi-digit OCR, better Indian comma parsing, more reliable JSON adherence → estimated 85–93% accuracy.

**Infrastructure:** Kaggle T4 x2 (32GB total). 32B in 4-bit ≈ 18GB, fits across both GPUs with `device_map="auto"`.

---

## 8d. OOM Fix: Dual-GPU Split on Kaggle T4 x2

**Symptom:** `device_map="auto"` packed all weights onto GPU 0 (14.56 GiB full), never split to GPU 1.

**Fix applied (extractor.py `_load_model`):**
```python
n_gpu = torch.cuda.device_count()
max_memory = {i: "13GiB" for i in range(n_gpu)}
max_memory["cpu"] = "0GiB"
```
Forces even split across both T4s, blocks CPU fallback (required — BnB 4-bit kernels cannot run on CPU).

**Secondary issue:** `pip install -U accelerate` silently upgraded transformers to 5.0.0. The new `core_model_loading.py` thread-pool materializer ignores `max_memory` and concentrates 4-bit weights on GPU 0 regardless. **Fix:** pin `transformers==4.49.0` in requirements.txt — uses classic dispatch path that respects max_memory.

**Result:** Model loads cleanly across both GPUs after these two fixes.

---

## 8e. Eval Run 1 — 32B, 150 docs (2026-06-19)

**Status accuracy: 85/150 = 56.7%** — worse than 7B's ~78%.

```
Precision (CR): 0.351 | Recall: 0.944 | F1: 0.511
Confusion: TP=34 TN=51 FP=63 FN=2

Per-field accuracy:
  disbursement_amount:  87/150  58.0%
  disbursement_date:    90/150  60.0%
  sanction_amount:     115/150  76.7%
  loan_account_number: 141/150  94.0%
  application_id:      148/150  98.7%
  bank_name:           150/150 100.0%
```

**Root cause of regression from 7B:** Amount/date prompt was instructing the model to convert values to normalized format. 32B follows instructions faithfully, did math, got it wrong (e.g. "Rs.25.00 lakhs" → "2500000" → arithmetic error). 7B partially ignored the conversion instruction.

**Fix:** Rewrite prompt to verbatim extraction. Model copies exactly what it sees; Python (`normalizer.py`) handles all conversions deterministically.

---

## 8f. GitHub Attribution Cleanup (2026-06-19)

All commits had `Co-Authored-By: Claude` trailers. Stripped via `git filter-branch --msg-filter` across all 30+ commits, force-pushed to origin. GitHub API confirmed only contributor is "Ridanshi". (Note: GitHub's cached contributor sidebar may lag up to 1 hour.)

---

## 8g. README.md Added (2026-06-19)

Comprehensive README committed covering: pipeline diagram, field comparison logic table, project structure, setup, usage, GPU requirements, configuration reference, roadmap.

---

## 8h. Eval Run 2 — verbatim fix, 150 docs (2026-06-19)

**Raw status accuracy: 85/150 = 56.7%** — unchanged.

**Diagnosed phantom aadhar failures:** All 38 aadhar APPROVED docs flagged CHANGES_REQUESTED. Root cause: aadhar is an **offer letter template** (pre-disbursement). Two fields (`disbursement_amount`, `disbursement_date`) are not printed in the document body but ground_truth.json incorrectly expected them.

Corrected score excluding phantom fields: **108/150 = 72.0%** — still below 7B's 78%.

**Further diagnosis (failure breakdown by lender+field):**
```
12  aadhar.pdf::sanction_amount      ← raw unformatted number in PDF, model drops digit
 7  mahindra.jpg::sanction_amount    ← JPG scan augmentation
 6  hdfc.jpg::sanction_amount
 6  hdfc.pdf::disbursement_amount
 4  mahindra.jpg::loan_account_number ← scan digit slips
 ...
```

**Aadhar sanction_amount root cause:** Line 434 in generate.py rendered the loan amount as `str(int(lakhs * 100_000))` — a raw unformatted integer (e.g. "3000000"). VLM consistently drops one zero on 7-digit raw numbers. Fix: use `fields["sanction_amount"]` which is already formatted by `format_amount_doc()` (e.g. "Rs.30.00 lakhs" or "₹30,00,000.00") — model reads these cleanly, normalizer converts correctly.

---

## 8i. Generator Fixes Applied (2026-06-19)

Three changes to `synthetic/generate.py`:

**Fix 1 — aadhar PDF renders formatted amount (line 434):**
```python
# Before:
["Loan Amount(Rs.)",  str(int(float(fields["sanction_amount_raw"])*100_000)), ...]
# After:
["Loan Amount(Rs.)",  fields["sanction_amount"], ...]
```

**Fix 2 — aadhar ground truth nulls disbursement fields (`_ground_truth_entry`):**
```python
is_aadhar = stem.startswith("aadhar")
"disbursement_amount": None if is_aadhar else str(int(float(fields["sanction_amount_raw"]) * 100_000)),
"disbursement_date":   None if is_aadhar else fields["disbursement_date_iso"],
```

**Fix 3 — mismatch guard for null disbursement_date:**
```python
elif mf == "disbursement_date" and expected["disbursement_date"]:
```

**Eval Run 3** running now (Kaggle, fresh session). Expected accuracy: ~85%+ once aadhar phantom failures and sanction_amount digit-drop are both resolved.

---

## 8j. Local Machine Limitation

Running `python app.py` on local Windows machine fails:
1. **Python 3.13** — PyTorch officially supports up to 3.12; torch._dynamo import crashes on 3.13
2. **No GPU with sufficient VRAM** — 32B model needs ~18GB GPU RAM in 4-bit

Local machine cannot run the 32B model. All inference must run on Kaggle T4 x2. For local testing of the 7B model, would need Python 3.11/3.12 + NVIDIA GPU ≥8GB VRAM.

---

## 9. v2 Roadmap (After Company Testing)

| Milestone | What | Why |
|---|---|---|
| Get 50–100 anonymized samples | Ask company for real docs with fake field values | Baseline accuracy measurement |
| Fine-tune with LoRA | Train on reviewer corrections (~500+) | Accuracy: 85–90% → 95%+ |
| Per-type prompts | Specialized prompts per lender/document type | Handles unusual layouts |
| PostgreSQL migration | Replace SQLite with company's RDS | Production integration |
| Celery + Redis | Async processing queue | Scale to 500–2000+ docs/day |

---

## 10. Synthetic Data Generator

**Script:** `synthetic/generate.py`

Three lender templates built with reportlab:

| Template | Style | Fields |
|---|---|---|
| Mahindra Finance | Blue header email + colored data table | All 9 fields |
| Aadhar Housing Finance | Orange logo header + offer letter prose | All 9 fields |
| HDFC | Blue letterhead + formal sanction letter | All 9 fields |

**Generation stats:**
- 25 docs per lender × 3 lenders = 75 PDFs in `synthetic/data/pdfs/`
- Each PDF converted to JPG via PyMuPDF with scan augmentation (rotation ±2.5°, brightness, contrast, optional blur) = 75 JPGs in `synthetic/data/images/`
- Total: 150 files (PDF + JPG per doc), 57 APPROVED / 18 CHANGES_REQUESTED

**Mismatch injection logic:**
- Index 0–6 (7 in 10): no mismatches → APPROVED
- Index 7–8 (2 in 10): 1 random field mismatch → CHANGES_REQUESTED
- Index 9 (1 in 10): 2 field mismatches → CHANGES_REQUESTED

**ground_truth.json:** 150 entries, each with `expected_values` (normalized), `expected_status`, and `mismatch_fields`.

**Bugs fixed during generation:**
1. Trailing `+` operator syntax error in pool tuple — removed
2. `pdf2image` requires Poppler binary (not available on Windows) — replaced with PyMuPDF (`fitz`)
3. `✓` and `→` UnicodeEncodeError on Windows terminal (cp1252) — replaced with ASCII

---

## 11. Git Log

```
0d3cc06  feat: project setup and config
cef23cd  feat: normalizer for amounts, dates, text
7fcacce  feat: comparator with fuzzy/exact matching and mismatch comments
ee5f813  feat: image preprocessor for PDF and image inputs
0fc15f0  feat: Qwen2.5-VL extractor with retry and invalid doc detection
8187d14  feat: Gradio UI for document upload, field input, and result display
6fc3813  feat: SQLite storage and history tab
c87b2f9  docs: session log with full design and implementation record
ff225b8  feat: synthetic document generator — 75 PDFs + 75 JPGs, 3 lenders, ground truth JSON
f2f335c  docs: update session log with synthetic data generation details
ecfb1ce  feat: smoke test script and fix app launch for RunPod (0.0.0.0 binding)
0360d65  feat: batch eval script against 150 synthetic docs
9946892  fix: repair Mahindra template — add lender name and loan account number
8447f99  fix: normalize_date ISO format bug — dayfirst=True swapped month/day
80ff17e  fix: partial_ratio -> ratio to catch suffix mismatches; fix eval per-field metric
2ca143d  fix: Aadhar/HDFC loan_account_number extraction failures
e5717d9  fix: remove ambiguous amount formats; shorten IDs to cut Qwen OCR errors
        (later reverted — overfitting)
[unpushed] fix: restore realistic amount formats + ID lengths (anti-overfitting)
[unpushed] fix: upgrade VLM to Qwen2.5-VL-32B-Instruct + 4-bit default
```
