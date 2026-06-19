"""
Synthetic loan document generator.
Produces PDF + JPG versions of 3 lender formats with randomised field values.
Outputs ground_truth.json with expected values and expected status per file.

Run: python synthetic/generate.py
"""

import json
import random
import sys
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF — no external binary needed on Windows
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE     = Path(__file__).parent
PDF_DIR  = BASE / "data" / "pdfs"
IMG_DIR  = BASE / "data" / "images"
GT_FILE  = BASE / "ground_truth.json"
PDF_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

# ── DATA POOLS ─────────────────────────────────────────────────────────────────
CUSTOMERS = [
    ("Rajesh Kumar",      None),
    ("Priya Sharma",      None),
    ("Sathish Kumar",     "UMA"),
    ("Mohammed Ali",      None),
    ("Anita Gupta",       "Vikram Gupta"),
    ("Suresh Nair",       None),
    ("Kavitha Reddy",     None),
    ("Ramesh Patel",      "Sunita Patel"),
    ("Lakshmi Devi",      None),
    ("Arjun Singh",       None),
    ("Fatima Begum",      "Abdul Rehman"),
    ("Venkatesh Rao",     None),
    ("Meena Krishnan",    None),
    ("Deepak Joshi",      "Rekha Joshi"),
    ("Zainab Khan",       None),
    ("Senthil Kumar",     "Malathi"),
    ("Usha Rani",         None),
    ("Balamurugan S",     None),
    ("Gomathi Devi",      "Shankar"),
    ("Ravi Shankar",      None),
    ("Sunitha Thomas",    None),
    ("Karthik Raj",       "Divya Karthik"),
    ("Nalini Mohan",      None),
    ("Prasad Reddy",      None),
    ("Indira Nair",       "Vijayan Nair"),
]

ADDRESSES = [
    "DOOR NO 32B, JALMA 3RD FLOOR, TEMPLEGREEN\nKANCHIPURAM, KANCHIPURAM, TAMIL NADU 602105",
    "NO 45, 2ND STREET, ANNA NAGAR\nCHENNAI, TAMIL NADU 600040",
    "FLAT 3A, LOTUS APARTMENTS, VELACHERY\nCHENNAI, TAMIL NADU 600042",
    "OLD NO 12 NEW NO 24, WEST MAMBALAM\nCHENNAI, TAMIL NADU 600033",
    "PLOT 7, SECTOR 4, TAMBARAM WEST\nTAMBARARUM, TAMIL NADU 600045",
    "NO 8, GANDHI ROAD, COIMBATORE\nCOIMBATORE, TAMIL NADU 641001",
    "D 14, NEHRU NAGAR, MADURAI\nMADURAI, TAMIL NADU 625014",
]

BRANCHES_MAHINDRA = [
    "MountRoad", "T.Nagar", "Velachery", "Tambaram", "Adyar",
    "Coimbatore", "Madurai", "Trichy", "Salem", "Vellore",
    "Perambur", "Porur", "Ambattur", "Guindy", "Sholinganallur",
]
BRANCHES_AADHAR = [
    "Tambaram", "Kanchipuram", "Velachery", "Perambur", "Avadi",
    "Sholinganallur", "Porur", "Ambattur", "Chrompet", "Pallavaram",
    "Poonamallee", "Sriperumbudur", "Uthandi", "Thiruvanmiyur", "Siruseri",
]
BRANCHES_HDFC = [
    "Nungambakkam", "Egmore", "Anna Nagar", "Mylapore", "Besant Nagar",
    "Ashok Nagar", "Vadapalani", "Guindy", "Perungudi", "Thoraipakkam",
    "Kilpauk", "Chetpet", "Royapettah", "Saidapet", "Kodambakkam",
]

LOAN_TYPES_MAHINDRA = ["Home Loan", "LAP", "LAP Non Individual", "Business Loan", "SME Loan"]
LOAN_TYPES_AADHAR   = ["Home Loan", "HOME LOAN QR", "Plot Loan", "Home Improvement Loan", "Home Extension Loan"]
LOAN_TYPES_HDFC     = ["Home Loan", "Home Loan - Regular", "Loan Against Property", "NRI Home Loan", "Home Construction Loan"]

CHANNEL_PARTNERS = ["Magicbricks", "99acres", "Housing.com", "NoBroker", "PropTiger", "Sulekha", "CommonFloor"]
RATES_OF_INTEREST = ["8.75", "9.00", "9.25", "9.50", "9.75", "10.00", "10.25", "13.75", "14.00"]
TENURES = ["120", "180", "240", "300", "360"]

# ── NUMBER HELPERS ─────────────────────────────────────────────────────────────
def indian_comma(n: int) -> str:
    s = str(abs(n))
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.append(rest)
    return ",".join(reversed(parts)) + "," + last3


def format_amount_doc(lakhs: float) -> str:
    rupees = int(lakhs * 100_000)
    choice = random.choice(["lakhs", "indian_comma", "plain_slash"])
    if choice == "lakhs":
        return f"Rs.{lakhs:.2f} lakhs"
    elif choice == "indian_comma":
        return f"₹{indian_comma(rupees)}.00"
    else:
        return f"Rs. {rupees:,}/-"


def format_date_doc(d: date) -> str:
    return random.choice([
        d.strftime("%d.%m.%Y"),
        d.strftime("%d %b %Y"),
        d.strftime("%d/%m/%Y"),
    ])


def random_date() -> date:
    return date(2026, random.randint(1, 6), random.randint(1, 28))


def random_lakhs() -> float:
    pool = (
        [round(x * 5,  1) for x in range(2,  10)] +
        [round(x * 10, 1) for x in range(5,  20)] +
        [round(x * 25, 1) for x in range(4,  12)]
    )
    return float(random.choice(pool))


def customer_display(first: str, second) -> str:
    return f"{first} & {second}" if second else first


# ── MISMATCH HELPERS ───────────────────────────────────────────────────────────
def make_mismatch(fields: dict, mismatch_count: int) -> dict:
    """Return expected_values that differ from document on mismatch_count fields."""
    expected = dict(fields)
    candidates = ["customer_name", "sanction_amount", "disbursement_date", "branch", "loan_type"]
    chosen = random.sample(candidates, min(mismatch_count, len(candidates)))
    for field in chosen:
        if field == "customer_name":
            # strip co-applicant if present, else add noise
            if " & " in expected["customer_name"]:
                expected["customer_name"] = expected["customer_name"].split(" & ")[0]
            else:
                expected["customer_name"] = expected["customer_name"] + " Kumar"
        elif field == "sanction_amount":
            original = float(expected["sanction_amount_raw"])
            expected["sanction_amount"] = str(int((original + random.choice([5, 10, 25])) * 100_000))
        elif field == "disbursement_date":
            d = date.fromisoformat(expected["disbursement_date"])
            expected["disbursement_date"] = date(d.year, d.month, min(d.day + 1, 28)).isoformat()
        elif field == "branch":
            expected["branch"] = expected["branch"] + " Branch"
        elif field == "loan_type":
            expected["loan_type"] = expected["loan_type"] + " Variant"
    return expected, chosen


# ── IMAGE AUGMENTATION ─────────────────────────────────────────────────────────
def augment_scan(img: Image.Image) -> Image.Image:
    img = img.rotate(random.uniform(-2.5, 2.5), expand=False, fillcolor=(255, 255, 255))
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.88, 1.05))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.90, 1.10))
    if random.random() < 0.35:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.3, 0.9)))
    return img


def pdf_to_jpg(pdf_path: Path, jpg_path: Path, dpi: int = 150):
    doc  = fitz.open(str(pdf_path))
    page = doc[0]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat)
    img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    img = augment_scan(img)
    img.save(str(jpg_path), "JPEG", quality=85)


# ── STYLES ─────────────────────────────────────────────────────────────────────
def _styles():
    s = getSampleStyleSheet()
    normal = ParagraphStyle("N",  fontName="Helvetica",        fontSize=9,  leading=13)
    bold   = ParagraphStyle("B",  fontName="Helvetica-Bold",   fontSize=9,  leading=13)
    small  = ParagraphStyle("S",  fontName="Helvetica",        fontSize=7.5,leading=11)
    title  = ParagraphStyle("T",  fontName="Helvetica-Bold",   fontSize=13, leading=18, alignment=TA_CENTER)
    right  = ParagraphStyle("R",  fontName="Helvetica",        fontSize=9,  leading=13, alignment=TA_RIGHT)
    center = ParagraphStyle("C",  fontName="Helvetica",        fontSize=9,  leading=13, alignment=TA_CENTER)
    return normal, bold, small, title, right, center


# ── TEMPLATE 1: MAHINDRA FINANCE (email / table format) ───────────────────────
def _mahindra_data(idx: int) -> dict:
    first, second = random.choice(CUSTOMERS)
    lakhs         = random_lakhs()
    disb_date     = random_date()
    app_id        = f"AP{random.randint(1000000000, 9999999999)}"
    loan_no       = f"LAPSEC{random.randint(100000000, 999999999)}"
    branch        = random.choice(BRANCHES_MAHINDRA)
    loan_type     = random.choice(LOAN_TYPES_MAHINDRA)
    channel       = random.choice(CHANNEL_PARTNERS)

    doc_fields = {
        "customer_name":      customer_display(first, second),
        "bank_name":          "Mahindra Finance",
        "loan_account_number": loan_no,
        "application_id":     app_id,
        "sanction_amount":    format_amount_doc(lakhs),
        "disbursement_amount": format_amount_doc(lakhs),
        "loan_type":          loan_type,
        "branch":             branch,
        "disbursement_date":  format_date_doc(disb_date),
        # raw values for ground truth
        "sanction_amount_raw":     str(lakhs),
        "disbursement_date_iso":   disb_date.isoformat(),
        "channel_partner":         channel,
    }
    return doc_fields


def build_mahindra_pdf(path: Path, fields: dict):
    normal, bold, small, title, right, center = _styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    W = A4[0] - 40*mm
    story = []

    # email header bar
    header_data = [[
        Paragraph(f'<font color="white"><b>Mahindra Finance</b></font>',
                  ParagraphStyle("WB", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white)),
        Paragraph(f'<font color="white">{fields["disbursement_date"]}</font>',
                  ParagraphStyle("WR", fontName="Helvetica", fontSize=9,
                                 textColor=colors.white, alignment=TA_RIGHT)),
    ]]
    header_tbl = Table(header_data, colWidths=[W*0.7, W*0.3])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR",  (0,0), (-1,-1), colors.white),
        ("PADDING",    (0,0), (-1,-1), 8),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('<font color="#555555">to me, DSA, Reviewer...</font>',
                           ParagraphStyle("grey", fontName="Helvetica", fontSize=8,
                                          textColor=colors.HexColor("#555555"))))
    story.append(Spacer(1, 5*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Sir/Madam,", normal))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "With reference to the below mail, please find attached the requested data.", normal))
    story.append(Spacer(1, 5*mm))

    # data table
    BLUE   = colors.HexColor("#1155CC")
    LBLUE  = colors.HexColor("#C9DAF8")
    rows = [
        ["Channel Partner Name", fields["channel_partner"]],
        ["Customer Name",        fields["customer_name"]],
        ["Loan Account No (LAN)", fields["loan_account_number"]],
        ["Application No",       fields["application_id"]],
        ["Disb Amount",          fields["disbursement_amount"]],
        ["Sanction Amount",      fields["sanction_amount"]],
        ["Disb Date",            fields["disbursement_date"]],
        ["Loan Type",            fields["loan_type"]],
        ["Branch",               fields["branch"]],
    ]
    tbl_data = [[
        Paragraph(r[0], ParagraphStyle("TH", fontName="Helvetica-Bold",
                                       fontSize=9, textColor=colors.white)),
        Paragraph(str(r[1]), ParagraphStyle("TD", fontName="Helvetica", fontSize=9)),
    ] for r in rows]

    tbl = Table(tbl_data, colWidths=[W*0.42, W*0.58])
    style = [
        ("BACKGROUND",  (0,0), (0,-1), BLUE),
        ("BACKGROUND",  (1,0), (1,-1), LBLUE),
        ("TEXTCOLOR",   (0,0), (0,-1), colors.white),
        ("FONTNAME",    (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 9),
        ("PADDING",     (0,0), (-1,-1), 6),
        ("ROWBACKGROUNDS", (1,0), (1,-1), [LBLUE, colors.white]),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#aaaaaa")),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
    ]
    for i in range(0, len(rows), 2):
        style.append(("BACKGROUND", (1,i), (1,i), LBLUE))
        if i+1 < len(rows):
            style.append(("BACKGROUND", (1,i+1), (1,i+1), colors.white))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Regards,", normal))
    story.append(Paragraph("Mount Road Branch — Disbursement Team", small))
    doc.build(story)


# ── TEMPLATE 2: AADHAR HOUSING FINANCE (offer letter) ─────────────────────────
def _aadhar_data(idx: int) -> dict:
    first, second = random.choice(CUSTOMERS)
    lakhs          = random_lakhs()
    disb_date      = random_date()
    app_id         = str(random.randint(300000000, 399999999))
    loan_no        = str(random.randint(300000000, 399999999))
    branch         = random.choice(BRANCHES_AADHAR)
    loan_type      = random.choice(LOAN_TYPES_AADHAR)
    rate           = random.choice(RATES_OF_INTEREST)
    tenure         = random.choice(TENURES)
    address        = random.choice(ADDRESSES)

    doc_fields = {
        "customer_name":       customer_display(first, second),
        "bank_name":           "Aadhar Housing Finance Limited",
        "loan_account_number": loan_no,
        "application_id":      app_id,
        "sanction_amount":     format_amount_doc(lakhs),
        "disbursement_amount": format_amount_doc(lakhs),
        "loan_type":           loan_type,
        "branch":              branch,
        "disbursement_date":   format_date_doc(disb_date),
        # extra fields for template rendering
        "sanction_amount_raw":   str(lakhs),
        "disbursement_date_iso": disb_date.isoformat(),
        "rate_of_interest":      rate,
        "tenure":                tenure,
        "address":               address,
    }
    return doc_fields


def build_aadhar_pdf(path: Path, fields: dict):
    normal, bold, small, title, right, center = _styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    W = A4[0] - 40*mm
    story = []

    # logo bar
    logo_data = [[
        Paragraph('<font color="white"><b>Aadhar</b></font>',
                  ParagraphStyle("logo", fontName="Helvetica-Bold", fontSize=16,
                                 textColor=colors.white)),
        Paragraph('<font color="white">Housing Finance Ltd.</font>',
                  ParagraphStyle("logoS", fontName="Helvetica", fontSize=10,
                                 textColor=colors.white, alignment=TA_RIGHT)),
    ]]
    logo_tbl = Table(logo_data, colWidths=[W*0.5, W*0.5])
    logo_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#E67E22")),
        ("PADDING",    (0,0), (-1,-1), 10),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(logo_tbl)

    # address bar
    addr_data = [[
        Paragraph("Registered Office: 805, Siddhivinayak Towers, Off S.G. Highway, Makarba, Ahmedabad 380051",
                  ParagraphStyle("addr", fontName="Helvetica", fontSize=7, textColor=colors.white)),
    ]]
    addr_tbl = Table(addr_data, colWidths=[W])
    addr_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#2C3E50")),
        ("PADDING",    (0,0), (-1,-1), 4),
    ]))
    story.append(addr_tbl)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("<b>Offer Letter</b>",
                           ParagraphStyle("OL", fontName="Helvetica-Bold", fontSize=13,
                                          alignment=TA_CENTER)))
    story.append(Spacer(1, 4*mm))

    ref_data = [[
        Paragraph("", normal),
        Paragraph(fields["disbursement_date"], right),
    ]]
    ref_tbl = Table(ref_data, colWidths=[W*0.6, W*0.4])
    ref_tbl.setStyle(TableStyle([("PADDING",(0,0),(-1,-1),0)]))
    story.append(ref_tbl)
    story.append(Spacer(1, 3*mm))

    addr_lines = fields["address"].replace("\n","<br/>")
    story.append(Paragraph(f"<b>{fields['customer_name']}</b>", bold))
    story.append(Paragraph(addr_lines, small))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Dear Sir/Madam,", normal))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"<b>Ref:</b> Your request for Loan vide Application No. {fields['application_id']}", normal))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "We thank you for choosing Aadhar Housing Finance Ltd. We are pleased to inform you that based on your loan "
        "application, we have in principle approved your Housing Loan / Plot Loan to you as per the terms and conditions "
        "mentioned below.", normal))
    story.append(Spacer(1, 4*mm))

    # loan details box
    ORANGE = colors.HexColor("#E67E22")
    LORANGE = colors.HexColor("#FAD7A0")
    story.append(Paragraph("<b>Loan Details</b>",
                           ParagraphStyle("LD", fontName="Helvetica-Bold", fontSize=9,
                                          backColor=ORANGE, textColor=colors.white,
                                          leftPadding=6, rightPadding=6,
                                          topPadding=4, bottomPadding=4)))
    story.append(Spacer(1, 1*mm))

    loan_rows = [
        ["Loan Amount(Rs.)",    fields["sanction_amount"],
         "Rate of Interest",    "FLOATING"],
        ["Tenure",              f"{fields['tenure']} months",
         "EMI Amount",          "Dis02yrs 10899"],
        ["Rate of Interest**",  f"{fields['rate_of_interest']} %",
         "b. Pro EMI Amount #", ""],
        ["RPLR %**",            "17.50",
         "c. Pro EMI period #", ""],
    ]
    detail_tbl_data = [[
        Paragraph(str(r[0]), ParagraphStyle("DH", fontName="Helvetica-Bold", fontSize=8)),
        Paragraph(str(r[1]), ParagraphStyle("DV", fontName="Helvetica", fontSize=8)),
        Paragraph(str(r[2]), ParagraphStyle("DH", fontName="Helvetica-Bold", fontSize=8)),
        Paragraph(str(r[3]), ParagraphStyle("DV", fontName="Helvetica", fontSize=8)),
    ] for r in loan_rows]
    detail_tbl = Table(detail_tbl_data, colWidths=[W*0.28, W*0.22, W*0.28, W*0.22])
    detail_tbl.setStyle(TableStyle([
        ("GRID",       (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (0,-1), LORANGE),
        ("BACKGROUND", (2,0), (2,-1), LORANGE),
        ("FONTSIZE",   (0,0), (-1,-1), 8),
        ("PADDING",    (0,0), (-1,-1), 5),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(detail_tbl)
    story.append(Spacer(1, 4*mm))

    # branch + loan type footer row
    footer_rows = [
        ["Loan Account No.", fields["loan_account_number"]],
        ["Application No.",  fields["application_id"]],
        ["Branch",           fields["branch"]],
        ["Loan Type",        fields["loan_type"]],
    ]
    footer_tbl_data = [[
        Paragraph(f"<b>{r[0]}</b>", normal),
        Paragraph(str(r[1]), normal),
    ] for r in footer_rows]
    footer_tbl = Table(footer_tbl_data, colWidths=[W*0.3, W*0.7])
    footer_tbl.setStyle(TableStyle([
        ("GRID",    (0,0), (-1,-1), 0.5, colors.grey),
        ("PADDING", (0,0), (-1,-1), 5),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#D5E8F0")),
    ]))
    story.append(footer_tbl)
    doc.build(story)


# ── TEMPLATE 3: HDFC LTD (sanction letter) ─────────────────────────────────────
def _hdfc_data(idx: int) -> dict:
    first, second = random.choice(CUSTOMERS)
    lakhs          = random_lakhs()
    disb_date      = random_date()
    app_id         = f"HDFC{random.randint(10000000, 99999999)}"
    loan_no        = f"HL{random.randint(1000000000, 9999999999)}"
    branch         = random.choice(BRANCHES_HDFC)
    loan_type      = random.choice(LOAN_TYPES_HDFC)
    rate           = random.choice(RATES_OF_INTEREST)
    address        = random.choice(ADDRESSES)

    doc_fields = {
        "customer_name":       customer_display(first, second),
        "bank_name":           "HDFC Ltd",
        "loan_account_number": loan_no,
        "application_id":      app_id,
        "sanction_amount":     format_amount_doc(lakhs),
        "disbursement_amount": format_amount_doc(lakhs),
        "loan_type":           loan_type,
        "branch":              branch,
        "disbursement_date":   format_date_doc(disb_date),
        "sanction_amount_raw":   str(lakhs),
        "disbursement_date_iso": disb_date.isoformat(),
        "rate_of_interest":      rate,
        "address":               address,
    }
    return doc_fields


def build_hdfc_pdf(path: Path, fields: dict):
    normal, bold, small, title, right, center = _styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    W = A4[0] - 40*mm
    story = []

    # header
    hdr_data = [[
        Paragraph('<font color="white"><b>HDFC Ltd.</b></font>',
                  ParagraphStyle("HH", fontName="Helvetica-Bold", fontSize=14, textColor=colors.white)),
        Paragraph('<font color="white">Home Loans | LAP | NRI Loans</font>',
                  ParagraphStyle("HS", fontName="Helvetica", fontSize=9,
                                 textColor=colors.white, alignment=TA_RIGHT)),
    ]]
    hdr_tbl = Table(hdr_data, colWidths=[W*0.5, W*0.5])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#003087")),
        ("PADDING",    (0,0), (-1,-1), 10),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(hdr_tbl)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("<b>SANCTION LETTER</b>",
                           ParagraphStyle("SL", fontName="Helvetica-Bold", fontSize=12,
                                          alignment=TA_CENTER,
                                          textColor=colors.HexColor("#003087"))))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#003087")))
    story.append(Spacer(1, 4*mm))

    ref_data = [[
        Paragraph(f"<b>Ref No:</b> {fields['application_id']}", normal),
        Paragraph(f"<b>Date:</b> {fields['disbursement_date']}", right),
    ]]
    ref_tbl = Table(ref_data, colWidths=[W*0.6, W*0.4])
    ref_tbl.setStyle(TableStyle([("PADDING",(0,0),(-1,-1),0)]))
    story.append(ref_tbl)
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph(f"<b>To,</b>", bold))
    story.append(Paragraph(f"<b>{fields['customer_name']}</b>", bold))
    addr_lines = fields["address"].replace("\n","<br/>")
    story.append(Paragraph(addr_lines, small))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Dear Sir/Madam,", normal))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        f"We are pleased to inform you that your application for a <b>{fields['loan_type']}</b> "
        f"has been sanctioned subject to terms and conditions mentioned below.", normal))
    story.append(Spacer(1, 4*mm))

    # sanction table
    DBLUE  = colors.HexColor("#003087")
    LBLUE2 = colors.HexColor("#D6E4F0")
    sanction_rows = [
        ["Loan Account Number",   fields["loan_account_number"]],
        ["Applicant Name",        fields["customer_name"]],
        ["Sanctioned Amount",     fields["sanction_amount"]],
        ["Disbursement Amount",   fields["disbursement_amount"]],
        ["Rate of Interest",      f"{fields['rate_of_interest']}% p.a. (Floating)"],
        ["Disbursement Date",     fields["disbursement_date"]],
        ["Loan Type",             fields["loan_type"]],
        ["Branch",                fields["branch"]],
    ]
    s_tbl_data = [[
        Paragraph(f"<b>{r[0]}</b>",
                  ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        Paragraph(str(r[1]), normal),
    ] for r in sanction_rows]
    s_tbl = Table(s_tbl_data, colWidths=[W*0.42, W*0.58])
    s_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), DBLUE),
        ("TEXTCOLOR",   (0,0), (0,-1), colors.white),
        ("ROWBACKGROUNDS", (1,0), (1,-1), [LBLUE2, colors.white]),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#aaaaaa")),
        ("PADDING",     (0,0), (-1,-1), 6),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(s_tbl)
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        "This sanction is valid for 90 days from the date of this letter. Please contact your branch for disbursal.",
        small))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(f"<b>Branch:</b> {fields['branch']} &nbsp;&nbsp; "
                            f"<b>HDFC Ltd.</b> — Authorised Signatory", small))
    doc.build(story)


# ── GROUND TRUTH BUILDER ───────────────────────────────────────────────────────
def _ground_truth_entry(stem: str, fields: dict, mismatch_fields: list) -> dict:
    """Build normalised expected_values and expected_status for ground_truth.json."""
    is_aadhar = stem.startswith("aadhar")
    expected = {
        "customer_name":       fields["customer_name"],
        "bank_name":           fields["bank_name"],
        "loan_account_number": fields["loan_account_number"],
        "application_id":      fields["application_id"],
        "sanction_amount":     str(int(float(fields["sanction_amount_raw"]) * 100_000)),
        "disbursement_amount": None if is_aadhar else str(int(float(fields["sanction_amount_raw"]) * 100_000)),
        "loan_type":           fields["loan_type"],
        "branch":              fields["branch"],
        "disbursement_date":   None if is_aadhar else fields["disbursement_date_iso"],
    }

    if mismatch_fields:
        for mf in mismatch_fields:
            if mf == "customer_name" and " & " in expected["customer_name"]:
                expected["customer_name"] = expected["customer_name"].split(" & ")[0]
            elif mf == "sanction_amount":
                v = int(expected["sanction_amount"])
                expected["sanction_amount"] = str(v + random.choice([500000, 1000000, 2500000]))
            elif mf == "disbursement_date" and expected["disbursement_date"]:
                d = date.fromisoformat(expected["disbursement_date"])
                expected["disbursement_date"] = date(d.year, d.month, min(d.day+1, 28)).isoformat()
            elif mf == "branch":
                expected["branch"] = expected["branch"] + " Branch"
            elif mf == "loan_type":
                expected["loan_type"] = expected["loan_type"] + " Variant"

    return {
        "expected_values":    expected,
        "expected_status":    "CHANGES_REQUESTED" if mismatch_fields else "APPROVED",
        "mismatch_fields":    mismatch_fields,
        "document_raw_fields": {
            k: v for k, v in fields.items()
            if k not in ("sanction_amount_raw", "disbursement_date_iso",
                         "rate_of_interest", "tenure", "address", "channel_partner")
        },
    }


# ── MAIN GENERATOR ─────────────────────────────────────────────────────────────
BUILDERS = {
    "mahindra": (build_mahindra_pdf, _mahindra_data),
    "aadhar":   (build_aadhar_pdf,   _aadhar_data),
    "hdfc":     (build_hdfc_pdf,     _hdfc_data),
}

def _mismatch_count(idx: int) -> int:
    """70 % no mismatch, 20 % single, 10 % double."""
    r = idx % 10
    if r < 7: return 0
    if r < 9: return 1
    return 2


def generate_all(n_per_lender: int = 25):
    ground_truth: dict = {}
    total_pdf = 0
    total_img = 0

    for lender, (build_fn, data_fn) in BUILDERS.items():
        print(f"\n  [{lender.upper()}] generating {n_per_lender} documents …")
        for idx in range(n_per_lender):
            fields = data_fn(idx)
            n_mismatch = _mismatch_count(idx)

            # decide which fields will be mismatched
            candidates = ["customer_name", "sanction_amount", "disbursement_date", "branch", "loan_type"]
            mismatch_fields = random.sample(candidates, n_mismatch) if n_mismatch else []

            stem   = f"{lender}_{idx+1:03d}"
            pdf_p  = PDF_DIR / f"{stem}.pdf"
            jpg_p  = IMG_DIR / f"{stem}.jpg"

            build_fn(pdf_p, fields)
            pdf_to_jpg(pdf_p, jpg_p)

            entry = _ground_truth_entry(stem, fields, mismatch_fields)
            ground_truth[f"{stem}.pdf"] = entry
            ground_truth[f"{stem}.jpg"] = entry

            total_pdf += 1
            total_img += 1
            sys.stdout.write(f"\r    {idx+1}/{n_per_lender} done")
            sys.stdout.flush()
        print()

    GT_FILE.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    print(f"\nDone: {total_pdf} PDFs  +  {total_img} JPGs  ->  {PDF_DIR.parent}")
    print(f"Done: ground_truth.json  ->  {GT_FILE}")
    approved  = sum(1 for v in ground_truth.values() if v["expected_status"] == "APPROVED") // 2
    changes   = sum(1 for v in ground_truth.values() if v["expected_status"] == "CHANGES_REQUESTED") // 2
    print(f"  APPROVED            : {approved}")
    print(f"  CHANGES_REQUESTED   : {changes}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    print(f"Generating {n} docs per lender ({n*3} total) …")
    generate_all(n_per_lender=n)
