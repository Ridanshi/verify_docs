import gradio as gr
from preprocessor import load_image
from extractor import extract_fields
from comparator import compare_fields

FIELD_LABELS = {
    "customer_name": "Customer Name",
    "bank_name": "Bank Name",
    "loan_account_number": "Loan Account Number",
    "application_id": "Application ID",
    "sanction_amount": "Sanction Amount",
    "disbursement_amount": "Disbursement Amount",
    "loan_type": "Loan Type",
    "branch": "Branch",
    "disbursement_date": "Disbursement Date",
}


def verify_document(
    document_file,
    customer_name, bank_name, loan_account_number, application_id,
    sanction_amount, disbursement_amount, loan_type, branch, disbursement_date,
):
    if document_file is None:
        return "No document uploaded.", "", ""

    try:
        file_path = document_file if isinstance(document_file, str) else document_file.name
        image = load_image(file_path)
    except ValueError as e:
        return str(e), "", ""
    except Exception as e:
        return f"Failed to load document: {e}", "", ""

    try:
        extracted = extract_fields(image)
    except Exception as e:
        return f"Extraction failed: {e}. Please try again.", "", ""

    expected = {
        "customer_name": customer_name,
        "bank_name": bank_name,
        "loan_account_number": loan_account_number,
        "application_id": application_id,
        "sanction_amount": sanction_amount,
        "disbursement_amount": disbursement_amount,
        "loan_type": loan_type,
        "branch": branch,
        "disbursement_date": disbursement_date,
    }

    result = compare_fields(extracted, expected)

    status_html = (
        '<div style="font-size:1.4em;font-weight:bold;color:green">✅ APPROVED</div>'
        if result.status == "APPROVED"
        else '<div style="font-size:1.4em;font-weight:bold;color:red">❌ CHANGES REQUESTED</div>'
    )

    comments_text = "\n".join(result.comments) if result.comments else "All fields matched."

    extracted_rows = "\n".join(
        f"| {FIELD_LABELS.get(k, k)} | {v or 'not found'} |"
        for k, v in result.extracted.items()
    )
    extracted_table = "| Field | Extracted Value |\n|---|---|\n" + extracted_rows

    return status_html, comments_text, extracted_table


with gr.Blocks(title="Loan Document Verifier") as demo:
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

if __name__ == "__main__":
    demo.launch()
