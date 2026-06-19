# Loan Document Verification Tool

Automated verification of loan disbursement documents using a vision-language model.

Reviewers currently open each sanctioned letter, disbursement letter, or banker
confirmation by hand, compare every field against the company's internal system
values, and either approve it or send it back for corrections. This tool automates
that workflow: it reads an uploaded document, extracts the relevant fields, compares
them against expected values, and returns **APPROVED** or **CHANGES REQUESTED** with
field-level mismatch comments.

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
   1. Preprocess image      (pdf2image / PIL → 1120×1120 RGB)
   2. Extract fields        (Qwen2.5-VL → document type + 9 fields as JSON)
   3. Validate document     (reject non-financial / near-empty uploads)
   4. Normalize values      (amounts → float, dates → ISO, text → lowercased)
   5. Compare fields        (fuzzy / exact / amount / date, per field type)
   6. Generate comments     (one line per mismatch)
   7. Persist result        (SQLite → results.db)
                      │
                      ▼
   APPROVED / CHANGES REQUESTED  +  mismatch comments  +  extracted fields
```

A single model call both classifies the document type
(`sanctioned_letter`, `disbursement_letter`, `offer_letter`, `banker_confirmation`,
or `invalid`) and extracts all fields — no separate classification step.

This is **zero-shot**: the pre-trained model is used as-is, with no fine-tuning.

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
| `sanction_amount` | Normalize → float → exact | `₹25,00,000` = `Rs.25.00 lakhs` |
| `disbursement_amount` | Normalize → float → exact | Same as above |
| `disbursement_date` | Parse → `YYYY-MM-DD` → exact | `31 Jan 2026` = `31.01.2026` |

The model extracts amounts and dates **verbatim** (exactly as printed); all
conversion is done deterministically in Python (`normalizer.py`), not by the model.

### Invalid document handling

Two layers reject bad uploads:
1. The model sets `document_type: "invalid"` for non-financial images.
2. The backend flags any document where fewer than 3 fields could be extracted.

Either triggers `CHANGES_REQUESTED` with an "Invalid document uploaded" comment.

---

## Project Structure

```
.
├── app.py            Gradio UI — Verify tab + History tab
├── extractor.py      Qwen2.5-VL load, prompt, JSON parse, retry, invalid detection
├── preprocessor.py   PDF / image → normalized PIL image
├── normalizer.py     normalize_amount, normalize_date, normalize_text
├── comparator.py     Field comparison → ComparisonResult (status + comments)
├── database.py       SQLite init, save_result, get_recent_results
├── config.py         Field lists, fuzzy thresholds, model ID
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
git clone https://github.com/Ridanshi/verify-docs.git
cd verify-docs
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
contrast, blur) to approximate real-world scanned input.

### Run batch evaluation

```bash
python eval.py                 # all 150 documents
python eval.py --limit 10      # quick sanity check on the first 10
python eval.py --pdfs-only     # PDFs only (75 documents)
python eval.py --out my.json   # custom output path
```

Reports status accuracy, precision / recall / F1 for the CHANGES_REQUESTED class,
per-field extraction accuracy, and a confusion matrix. Per-document detail is
written to `eval_results.json`.

### Run tests

```bash
pytest
```

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
routing, fuzzy thresholds, and the model ID. Adjusting a threshold or swapping the
model is a one-line change there.

---

## Roadmap

The current version is zero-shot and standalone, intended for the company to test
before integration. Planned next steps:

| Milestone | What | Why |
|---|---|---|
| Confidence / abstention layer | Auto-approve only high-confidence matches; route uncertain ones to a human | Safe deployment without chasing model perfection |
| Real-data fine-tuning | LoRA on accumulated reviewer corrections | Raise accuracy beyond the zero-shot ceiling |
| PostgreSQL migration | Replace SQLite with the company's database | Production integration |
| Async processing | Queue (Celery + Redis) for high throughput | Scale to 500–2000+ documents/day |

Fine-tuning is deliberately deferred: there is no real training data yet, and
training on the synthetic set would overfit to the three templates. Real reviewer
corrections collected during production use are what will improve accuracy.
