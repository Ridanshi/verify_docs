# Main app — launches the Gradio web UI.
#
# Three tabs:
#   1. Verify Document  — upload a document + type expected values → get verdict
#   2. Auto Compare     — upload one screenshot (system left, document right) → auto verdict
#   3. History          — see the last 50 verification results from the database

import os
import re
import gradio as gr
from preprocessor import load_image
from extractor import extract_fields, extract_from_combined_screenshot
from comparator import compare_fields
from database import init_db, save_result, get_recent_results
from db_lookup import (
    lookup_by_lan,
    fetch_ops_queue,
    LookupError,
    AmbiguousRecordError,
    DBConnectionError,
)

# Set up the SQLite database on startup (creates the file if it doesn't exist)
init_db()

# Human-readable labels for each internal field key
FIELD_LABELS = {
    "customer_name":      "Customer Name",
    "bank_name":          "Bank Name",
    "loan_account_number":"Loan Account Number",
    "application_id":     "Application ID",
    "sanction_amount":    "Sanction Amount",
    "disbursement_amount":"Disbursement Amount",
    "loan_type":          "Loan Type",
    "branch":             "Branch",
    "disbursement_date":  "Disbursement Date",
}


def verify_document(
    document_file,
    customer_name, bank_name, loan_account_number, application_id,
    sanction_amount, disbursement_amount, loan_type, branch, disbursement_date,
):
    """Handler for the Verify Document tab.

    User uploads a document and manually types the expected values.
    The model extracts fields from the document, then compares against what was typed.
    """
    if document_file is None:
        return "No document uploaded.", "", ""

    # Load and preprocess the uploaded file (PDF render or image enhance)
    try:
        file_path = document_file if isinstance(document_file, str) else document_file.name
        filename  = os.path.basename(file_path)
        image     = load_image(file_path)
    except ValueError as e:
        return str(e), "", ""
    except Exception as e:
        return f"Failed to load document: {e}", "", ""

    # Run the model on the document image
    try:
        extracted = extract_fields(image)
    except Exception as e:
        return f"Extraction failed: {e}. Please try again.", "", ""

    # Build the expected values dict from what the user typed
    expected = {
        "customer_name":       customer_name,
        "bank_name":           bank_name,
        "loan_account_number": loan_account_number,
        "application_id":      application_id,
        "sanction_amount":     sanction_amount,
        "disbursement_amount": disbursement_amount,
        "loan_type":           loan_type,
        "branch":              branch,
        "disbursement_date":   disbursement_date,
    }

    # Guard: if every expected field is blank, there's nothing to compare against.
    # Without this check the tool would silently return APPROVED on an empty form.
    if not any(v and str(v).strip() for v in expected.values()):
        return (
            '<div style="font-size:1.4em;font-weight:bold;color:orange">NO EXPECTED VALUES</div>',
            "No expected field values were entered — nothing to compare against.\n\n"
            "Either:\n"
            "  • Fill in the fields on the left, OR\n"
            "  • Use the Auto Compare tab and upload a screenshot showing both the system panel and the document.",
            "",
        )

    result = compare_fields(extracted, expected)

    # Save to history regardless of outcome
    save_result(filename, result.status, result.extracted, expected, result.comments)

    # Colour-coded status badge
    if result.status == "APPROVED":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:green">APPROVED</div>'
    elif result.status == "NEEDS_REVIEW":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:orange">NEEDS REVIEW</div>'
    else:
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:red">CHANGES REQUESTED</div>'

    comments_text = "\n".join(result.comments) if result.comments else "All fields matched."

    # Show what the model actually extracted, field by field
    extracted_rows  = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or 'not found'} |"
        for k, v in result.extracted.items()
    )
    extracted_table = "| Field | Extracted Value |\n|---|---|\n" + extracted_rows

    return status_html, comments_text, extracted_table


def auto_compare(screenshot_file):
    """Handler for the Auto Compare tab.

    User uploads one screenshot showing the system panel on the left and the
    loan document on the right. The model reads both sides automatically —
    no manual typing needed.
    """
    if screenshot_file is None:
        return "No screenshot uploaded.", "", "", ""

    try:
        file_path = screenshot_file if isinstance(screenshot_file, str) else screenshot_file.name
        image     = load_image(file_path)
    except Exception as e:
        return f"Failed to load screenshot: {e}", "", "", ""

    # Two model calls: one for the left (system) panel, one for the right (document)
    try:
        expected, extracted = extract_from_combined_screenshot(image)
    except Exception as e:
        return f"Extraction failed: {e}. Please try again.", "", "", ""

    result = compare_fields(extracted, expected)

    save_result("auto_compare", result.status, result.extracted, expected, result.comments)

    if result.status == "APPROVED":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:green">APPROVED</div>'
    elif result.status == "NEEDS_REVIEW":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:orange">NEEDS REVIEW</div>'
    else:
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:red">CHANGES REQUESTED</div>'

    comments_text = "\n".join(result.comments) if result.comments else "All fields matched."

    # Show what was read from each side so the user can verify the model understood both panels
    system_rows  = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or '—'} |"
        for k, v in expected.items()
    )
    system_table = "**System values (left panel):**\n\n| Field | Value |\n|---|---|\n" + system_rows

    extracted_rows  = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or 'not found'} |"
        for k, v in result.extracted.items()
    )
    extracted_table = "**Document values (right panel):**\n\n| Field | Extracted Value |\n|---|---|\n" + extracted_rows

    return status_html, comments_text, system_table, extracted_table


_LAN_PATTERN = re.compile(r"^[A-Za-z0-9]{6,25}$")


def _lan_from_filename(filename):
    """Strip extension and surrounding whitespace; return the LAN candidate.

    Reviewer convention: save the document as <Loan_Account_Number>.<ext>
    before uploading. The filename stem IS the case identifier — this is the
    only trusted source of "which DB record to compare against". The doc's
    own LAN is never trusted (a wrong doc may be attached to the case).
    """
    stem = os.path.splitext(filename)[0].strip()
    return stem


def db_verify(document_file):
    """Handler for the DB Verify tab.

    Filename-driven workflow: the uploaded file MUST be named after the case
    LAN (e.g. LAPSEC000007708.pdf). The app fetches that exact DB record and
    compares it against fields extracted from the document.

    This catches the "wrong doc attached to case" scenario — if reviewer
    is working on case X but attaches the document for case Y, every field
    will mismatch and the verdict will be CHANGES REQUESTED.
    """
    if document_file is None:
        return "No document uploaded.", "", "", ""

    try:
        file_path = document_file if isinstance(document_file, str) else document_file.name
        filename  = os.path.basename(file_path)
        image     = load_image(file_path)
    except Exception as e:
        return f"Failed to load document: {e}", "", "", ""

    # Source of truth: the filename. NOT what the model reads from the document.
    lan = _lan_from_filename(filename)

    if not _LAN_PATTERN.match(lan):
        return (
            '<div style="font-size:1.4em;font-weight:bold;color:red">INVALID FILENAME</div>',
            f"Filename '{filename}' does not look like a Loan Account Number.\n\n"
            "Rename the file to match the case LAN before uploading.\n"
            "Example: LAPSEC000007708.pdf, AP0020067658.png, 301047981.jpg",
            "", "",
        )

    # Fetch the case from DB — hard stop if no record or ambiguous.
    try:
        db_record = lookup_by_lan(lan)
    except (LookupError, AmbiguousRecordError) as e:
        return (
            '<div style="font-size:1.4em;font-weight:bold;color:red">NO RECORD FOUND</div>',
            f"{e}\n\nFilename LAN: {lan}\n\n"
            "Either the LAN is wrong (check filename) or the case is not in the ops queue.",
            f"Filename LAN: **{lan}**",
            "",
        )
    except DBConnectionError as e:
        return (
            '<div style="font-size:1.4em;font-weight:bold;color:orange">DB UNAVAILABLE</div>',
            str(e),
            "", "",
        )

    # Extract document fields via VLM (after DB lookup, so we fail fast on bad filename)
    try:
        extracted = extract_fields(image)
    except Exception as e:
        return f"Extraction failed: {e}. Please try again.", "", "", ""

    # Build expected dict from DB values — convert amounts/dates to strings for comparator
    disb_date = db_record.get("disbursement_date")
    expected  = {
        "customer_name":       db_record.get("customer_name"),
        "bank_name":           db_record.get("bank_name"),
        "loan_account_number": db_record.get("loan_account_number"),
        "application_id":      db_record.get("application_id"),
        "sanction_amount":     str(int(db_record["sanction_amount"]))  if db_record.get("sanction_amount")  else None,
        "disbursement_amount": str(int(db_record["disbursement_amount"])) if db_record.get("disbursement_amount") else None,
        "loan_type":           None,
        "branch":              db_record.get("branch"),
        "disbursement_date":   disb_date.isoformat() if disb_date else None,
    }

    result = compare_fields(extracted, expected)
    save_result(filename, result.status, result.extracted, expected, result.comments)

    if result.status == "APPROVED":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:green">APPROVED</div>'
    elif result.status == "NEEDS_REVIEW":
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:orange">NEEDS REVIEW</div>'
    else:
        status_html = '<div style="font-size:1.4em;font-weight:bold;color:red">CHANGES REQUESTED</div>'

    comments_text = "\n".join(result.comments) if result.comments else "All fields matched."

    # Show the DB record that was matched so reviewer can confirm it's the right one
    db_rows   = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or '—'} |"
        for k, v in expected.items() if v
    )
    db_table  = f"**DB Record for case LAN: {lan}** (from filename)\n\n| Field | DB Value |\n|---|---|\n" + db_rows

    ext_rows  = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or 'not found'} |"
        for k, v in result.extracted.items()
    )
    ext_table = "**Document (extracted by model):**\n\n| Field | Extracted Value |\n|---|---|\n" + ext_rows

    return status_html, comments_text, db_table, ext_table


def load_ops_queue():
    """Fetch current ops-pending disbursements for the queue display."""
    rows = fetch_ops_queue()
    if not rows:
        return [["DB not connected or queue is empty.", "", "", "", ""]]
    return [
        [
            r.get("loan_account_number", ""),
            r.get("customer_name", ""),
            r.get("bank_name", ""),
            r.get("branch", ""),
            str(r.get("disbursement_date", "")),
        ]
        for r in rows
    ]


def load_history():
    """Fetch the last 50 verifications from the database for the History tab."""
    rows = get_recent_results(limit=50)
    if not rows:
        return [["No verifications yet.", "", "", ""]]
    return [
        [r["id"], r["timestamp"], r["filename"], r["status"], r["comments"] or "—"]
        for r in rows
    ]


# ── UI layout ───────────────────────────────────────────────────────────────────

with gr.Blocks(title="Loan Document Verifier") as demo:

    with gr.Tab("Verify Document"):
        gr.Markdown("## Loan Document Verification Tool")
        gr.Markdown("Upload a document and enter expected field values. The tool will extract and compare.")

        with gr.Row():
            with gr.Column():
                doc_input = gr.File(
                    label="Upload Document (PDF / JPG / PNG / TIFF)",
                    file_types=[".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"],
                )
                gr.Markdown("### Expected Field Values")
                f_customer_name       = gr.Textbox(label="Customer Name")
                f_bank_name           = gr.Textbox(label="Bank Name")
                f_loan_account_no     = gr.Textbox(label="Loan Account Number")
                f_application_id      = gr.Textbox(label="Application ID")
                f_sanction_amount     = gr.Textbox(label="Sanction Amount (e.g. 6350000 or Rs.63.5 lakhs)")
                f_disbursement_amount = gr.Textbox(label="Disbursement Amount")
                f_loan_type           = gr.Textbox(label="Loan Type")
                f_branch              = gr.Textbox(label="Branch")
                f_disbursement_date   = gr.Textbox(label="Disbursement Date (e.g. 2026-01-31)")
                submit_btn            = gr.Button("Verify Document", variant="primary")

            with gr.Column():
                status_out    = gr.HTML(label="Status")
                comments_out  = gr.Textbox(label="Comments / Mismatches", lines=6, interactive=False)
                extracted_out = gr.Markdown(label="Extracted Fields")

        submit_btn.click(
            fn=verify_document,
            inputs=[
                doc_input,
                f_customer_name, f_bank_name, f_loan_account_no, f_application_id,
                f_sanction_amount, f_disbursement_amount, f_loan_type, f_branch, f_disbursement_date,
            ],
            outputs=[status_out, comments_out, extracted_out],
        )

    with gr.Tab("Auto Compare"):
        gr.Markdown("## Auto Compare — Screenshot Mode")
        gr.Markdown(
            "Take a screenshot showing the **system panel on the left** and the "
            "**loan document on the right**, then upload it here. "
            "No manual entry needed."
        )
        with gr.Row():
            with gr.Column():
                screenshot_input = gr.File(
                    label="Upload Screenshot (JPG / PNG)",
                    file_types=[".jpg", ".jpeg", ".png"],
                )
                auto_btn = gr.Button("Compare", variant="primary")
            with gr.Column():
                auto_status_out   = gr.HTML(label="Status")
                auto_comments_out = gr.Textbox(label="Mismatches", lines=5, interactive=False)
                auto_system_out   = gr.Markdown(label="System Values")
                auto_doc_out      = gr.Markdown(label="Document Values")

        auto_btn.click(
            fn=auto_compare,
            inputs=[screenshot_input],
            outputs=[auto_status_out, auto_comments_out, auto_system_out, auto_doc_out],
        )

    with gr.Tab("DB Verify"):
        gr.Markdown("## DB Verify — Filename-driven case match")
        gr.Markdown(
            "**Rename the document to match the case Loan Account Number before uploading.**\n\n"
            "Examples: `LAPSEC000007708.pdf`, `AP0020067658.png`, `301047981.jpg`\n\n"
            "The tool fetches that exact case from the ops queue and compares every "
            "DB field against what the model reads from the document. "
            "If a wrong document is attached to a case, every field will mismatch — "
            "verdict will be CHANGES REQUESTED."
        )
        with gr.Row():
            with gr.Column(scale=1):
                db_doc_input = gr.File(
                    label="Upload Document (PDF / JPG / PNG / TIFF)",
                    file_types=[".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"],
                )
                db_verify_btn = gr.Button("Verify from DB", variant="primary")
                gr.Markdown("---")
                gr.Markdown("### Current Ops Queue")
                queue_refresh_btn = gr.Button("Refresh Queue", variant="secondary")
                queue_table = gr.Dataframe(
                    headers=["LAN", "Customer", "Bank", "Branch", "Disb. Date"],
                    datatype=["str", "str", "str", "str", "str"],
                    interactive=False,
                    wrap=True,
                )

            with gr.Column(scale=2):
                db_status_out   = gr.HTML(label="Status")
                db_comments_out = gr.Textbox(label="Comments / Mismatches", lines=6, interactive=False)
                db_record_out   = gr.Markdown(label="DB Record (Expected)")
                db_doc_out      = gr.Markdown(label="Document (Extracted)")

        db_verify_btn.click(
            fn=db_verify,
            inputs=[db_doc_input],
            outputs=[db_status_out, db_comments_out, db_record_out, db_doc_out],
        )
        queue_refresh_btn.click(fn=load_ops_queue, inputs=[], outputs=[queue_table])
        demo.load(fn=load_ops_queue, inputs=[], outputs=[queue_table])

    with gr.Tab("History"):
        gr.Markdown("## Past Verifications")
        refresh_btn = gr.Button("Refresh", variant="secondary")
        history_table = gr.Dataframe(
            headers=["ID", "Timestamp", "Filename", "Status", "Comments"],
            datatype=["number", "str", "str", "str", "str"],
            interactive=False,
            wrap=True,
        )
        refresh_btn.click(fn=load_history, inputs=[], outputs=[history_table])
        demo.load(fn=load_history, inputs=[], outputs=[history_table])


if __name__ == "__main__":
    # share=True creates a public gradio.live link — needed on Kaggle where
    # localhost isn't accessible from outside the notebook
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)
