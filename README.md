# Loan Document Verification Tool

Automated verification of loan disbursement documents using a vision-language model.

Reviewers currently open each sanctioned letter, disbursement letter, or banker
confirmation by hand, compare every field against the company's internal system
values, and either approve it or send it back for corrections. This tool automates
that workflow: it reads an uploaded document, extracts the relevant fields, compares
them against expected values, and returns **APPROVED**, **CHANGES_REQUESTED**, or
**NEEDS_REVIEW** with field-level mismatch comments.

---

## How It Works

```
Document (PDF / JPG / PNG / TIFF) + expected field values
                      │
                      ▼
              Gradio web UI
                      │
                      ▼
        Python backend (synchronous)
   1. Preprocess image      (PyMuPDF / PIL → 1120×1120 RGB;
                             JPGs also get deskew + sharpen + contrast)
   2. Extract fields        (Qwen2.5-VL → document type + 11 fields as JSON)
   3. Validate document     (reject non-financial / near-empty uploads)
   4. Normalize values      (amounts → float, dates → ISO, text → lowercased)
   5. Reconcile amounts     (cross-validate digit vs. word representation)
   6. Compare fields        (fuzzy / exact / amount / date, per field type)
   7. Generate comments     (one line per mismatch)
   8. Persist result        (SQLite → results.db)
                      │
                      ▼
   APPROVED / CHANGES_REQUESTED / NEEDS_REVIEW  +  comments  +  extracted fields
```

A single model call both classifies the document type
(`sanctioned_letter`, `disbursement_letter`, `offer_letter`, `banker_confirmation`,
or `invalid`) and extracts all fields — no separate classification step.

This is **zero-shot**: the pre-trained model is used as-is, with no fine-tuning.

---

## Output Statuses

| Status | Meaning |
|---|---|
| `APPROVED` | All extracted fields match expected values |
| `CHANGES_REQUESTED` | One or more fields mismatch — document must be corrected |
| `NEEDS_REVIEW` | Amount digit/word representations conflict and cannot be resolved automatically — route to human |

---

## Fields Extracted & Comparison Logic

Nine fields are extracted from every document and compared against expected values.
The comparison method is chosen per field, because different fields tolerate
different kinds of difference:

| Field | Match method | Why |
|---|---|---|
| `customer_name` | Fuzzy (threshold 85) | Casing, co-applicants, abbreviations |
| `bank_name` | Fuzzy (threshold 80) | Abbreviations, suffixes (Ltd / Limited) |
| `branch` | Fuzzy (threshold 80) | Naming variations |
| `loan_type` | Fuzzy (threshold 80) | "Home Loan" vs "Housing Loan" |
| `loan_account_number` | Exact string | One wrong digit = wrong record |
| `application_id` | Exact string | One wrong digit = wrong record |
| `sanction_amount` | Digit + word cross-validation → float → exact | See below |
| `disbursement_amount` | Digit + word cross-validation → float → exact | See below |
| `disbursement_date` | Parse → `YYYY-MM-DD` → exact | `31 Jan 2026` = `31.01.2026` |

The model extracts amounts and dates **verbatim** (exactly as printed); all
conversion is done deterministically in Python (`normalizer.py`), not by the model.

### Amount cross-validation

Indian loan documents print amounts twice — once in digits and once in words
(e.g. `Rs.63.50 lakhs (Rupees Sixty Three Lakh Fifty Thousand Only)`). The model
reads both. The comparator reconciles them:

- Digits and words agree → use words (authoritative), compare to expected
- Digits and words differ by a 10× or 100× factor → words recover the dropped zeros, compare to expected
- Digits and words disagree in a way that cannot be explained by a scale error → `NEEDS_REVIEW`
- 10× digit error with no words present → `NEEDS_REVIEW`

This fixes the most common VLM failure mode on large Indian numbers (digit drop).

### Invalid document handling

Two layers reject bad uploads:
1. The model sets `document_type: "invalid"` for non-financial images.
2. The backend flags any document where fewer than 3 fields could be extracted.

Either triggers `CHANGES_REQUESTED` with an "Invalid document uploaded" comment.

---

## Project Structure

```
.
├── app.py            Gradio UI — Verify tab (3-status display) + History tab
├── extractor.py      Qwen2.5-VL load, prompt, JSON parse, retry, invalid detection
├── preprocessor.py   PDF / image → normalized PIL image; scan enhancement for JPGs
├── normalizer.py     normalize_amount, normalize_date, normalize_text, words_to_number
├── comparator.py     Field comparison + amount reconciliation → ComparisonResult
├── database.py       SQLite init, save_result, get_recent_results
├── config.py         Field lists, fuzzy thresholds, model ID, AMOUNT_WORD_FIELDS map
├── eval.py           Batch evaluation against the synthetic test set
├── run_smoke_test.py Single-document end-to-end smoke test
├── requirements.txt
├── tests/            Unit tests for normalizer, comparator, preprocessor, database
└── synthetic/
    ├── generate.py        Synthetic document generator (3 lenders)
    ├── ground_truth.json  150 entries: expected values + status per file
    └── data/              Generated PDFs and JPGs (not tracked)
```

---

## Setup

Requires Python 3.10+. A GPU is needed to run the model
(`Qwen/Qwen2.5-VL-32B-Instruct` needs ~18 GB in 4-bit; see notes below).

```bash
git clone https://github.com/Ridanshi/verify_docs.git
cd verify_docs
pip install -r requirements.txt
```

---

## Usage

### Launch the web UI

```bash
python app.py        # serves on http://0.0.0.0:7860
```

The UI has two tabs:
- **Verify Document** — upload a document, enter the expected field values, get a verdict.
- **History** — the last 50 verifications, read from `results.db`.

### Generate synthetic test data

```bash
python synthetic/generate.py
```

Produces 150 documents (75 PDFs + 75 JPGs) across three lender templates
(Mahindra Finance, Aadhar Housing Finance, HDFC) with a matching
`ground_truth.json`. The JPGs include scan augmentation (rotation, brightness,
contrast, blur) to approximate real-world scanned input. All amounts are rendered
in both digit and word form to match real Indian loan documents.

### Run batch evaluation

```bash
python eval.py                    # all 150 documents
python eval.py --limit 10         # quick sanity check on the first 10
python eval.py --pdfs-only        # PDFs only (75 documents)
python eval.py --lender mahindra  # one lender only (mahindra / aadhar / hdfc)
python eval.py --out my.json      # custom output path
```

Reports status accuracy, precision / recall / F1 for the CHANGES_REQUESTED class,
NEEDS_REVIEW rate, per-field extraction accuracy, and a confusion matrix.
Per-document detail is written to `eval_results.json`.

### Run tests

```bash
pytest
```

43 unit tests covering normalizer, comparator (including amount reconciliation),
preprocessor, and database.

---

## Running the model on a GPU

The 32B model does not fit on a single 16 GB GPU. Two setups work:

- **Single GPU ≥ 24 GB** (recommended): the model loads whole, no special config.
- **Dual 16 GB GPUs** (e.g. Kaggle T4 ×2): the model is split across both GPUs via
  an explicit `max_memory` map to prevent CPU offload (which 4-bit kernels do not
  support). This path requires `transformers==4.49.0` — newer versions concentrate
  the quantized weights on one GPU and OOM. The pin is set in `requirements.txt`.

4-bit quantization is enabled by default via the `USE_4BIT=1` environment variable.

---

## Configuration

`config.py` is the single source of truth for field definitions, comparison
routing, fuzzy thresholds, the model ID, and the `AMOUNT_WORD_FIELDS` mapping that
links each amount field to its word-form companion. Adjusting a threshold or
swapping the model is a one-line change there.

---

## Roadmap

The current version is zero-shot and standalone, intended for the company to test
before integration. Planned next steps:

| Milestone | What | Why |
|---|---|---|
| Real-data fine-tuning | LoRA on accumulated reviewer corrections | Raise accuracy beyond the zero-shot ceiling |
| PostgreSQL migration | Replace SQLite with the company's database | Production integration |
| Async processing | Queue (Celery + Redis) for high throughput | Scale to 500–2000+ documents/day |
| Per-lender prompts | Specialized prompts per lender layout | Handle unusual or new lender formats |

Fine-tuning is deliberately deferred: there is no real training data yet, and
training on the synthetic set would overfit to the three templates. Real reviewer
corrections collected during production use are what will improve accuracy.
