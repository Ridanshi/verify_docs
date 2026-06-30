# seed_db.py — wipe cloned DB and re-insert clean test data for DB Verify tab.
#
# TRUNCATES lending_partners, leads, applications, disbursements (CASCADE),
# then inserts exact test records derived from real sample documents + bulk
# random records for realism.
#
# Pinned test records:
#   LAN AP0020067658     → Sathish Kumar & UMA, 195L, Mahindra Finance, MountRoad
#   LAN 301047981        → SUGUNA K, 9L sanction/10.67L disb, Aadhar Housing Finance, Tambaram
#   LAN LAPSEC000007708  → Zainab Medicals, 63.5L, Mahindra Finance, T.Nagar (mismatch test)
#
# Usage:
#   python seed_db.py           → wipe + re-insert
#   python seed_db.py --dry-run → print plan, no writes

import os
import sys
import random
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv

# ── Seed data pools ──────────────────────────────────────────────────────────

FIRST_NAMES = [
    "Rajesh", "Priya", "Amit", "Sunita", "Vikram", "Kavitha", "Suresh",
    "Anita", "Rahul", "Deepa", "Manoj", "Rekha", "Arun", "Meena", "Sanjay",
    "Lakshmi", "Ravi", "Geeta", "Prakash", "Shobha", "Harish", "Uma",
    "Ganesh", "Saritha", "Krishnan", "Padma", "Venkat", "Nirmala", "Ashok",
    "Jayanthi", "Mohan", "Sudha", "Bala", "Radha", "Ramesh", "Usha",
    "Senthil", "Divya", "Karthik", "Pooja", "Murugan", "Geetha", "Selvam",
]

LAST_NAMES = [
    "Kumar", "Sharma", "Singh", "Reddy", "Nair", "Patel", "Rao", "Iyer",
    "Verma", "Gupta", "Joshi", "Mehta", "Shah", "Pillai", "Menon",
    "Agarwal", "Mishra", "Pandey", "Tiwari", "Yadav", "Bhat", "Shetty",
    "Naidu", "Murugan", "Krishnamurthy", "Subramanian", "Venkatesh",
]

BRANCHES = [
    "T.Nagar", "MountRoad", "Anna Nagar", "Velachery", "Tambaram",
    "Andheri", "Bandra", "Powai", "Thane", "Pune Central",
    "Connaught Place", "Lajpat Nagar", "Dwarka", "Rohini",
    "Koramangala", "Indiranagar", "Whitefield", "Jayanagar",
    "Banjara Hills", "Jubilee Hills", "Hitech City",
    "Salt Lake", "Park Street", "Alipore",
    "Vashi", "Nerul", "Kharghar",
    "Mylapore", "Adyar", "Perambur", "Chromepet",
]

# (name, lan_prefix, lan_format_fn, lan_regex)
LENDING_PARTNERS = [
    ("Mahindra Finance",              "LAPSEC",  lambda: "LAPSEC" + str(random.randint(100000000, 999999999)), r"^LAPSEC\d{9}$"),
    ("Aadhar Housing Finance Limited","AHFL",    lambda: str(random.randint(100000000, 999999999)),             r"^\d{9}$"),
    ("HDFC Bank",                     "HL",      lambda: "HL" + str(random.randint(1000000000, 9999999999)),    r"^HL\d{10}$"),
    ("State Bank of India",           "SBI",     lambda: str(random.randint(10000000000, 99999999999)),         r"^\d{11}$"),
    ("ICICI Bank",                    "ICICI",   lambda: "ICICI" + str(random.randint(100000000, 999999999)),   r"^ICICI\d{9}$"),
    ("Axis Bank",                     "AXIS",    lambda: "AXIS" + str(random.randint(100000000, 999999999)),    r"^AXIS\d{9}$"),
    ("Kotak Mahindra Bank",           "KMB",     lambda: "KMB" + str(random.randint(100000000, 999999999)),     r"^KMB\d{9}$"),
    ("Bank of Baroda",                "BOB",     lambda: "BOB" + str(random.randint(100000000, 999999999)),     r"^BOB\d{9}$"),
]

AMOUNT_LAKHS = [
    9, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 63.5,
    70, 75, 80, 90, 100, 120, 150, 175, 195, 200, 250, 300,
]


def lakhs_to_paise(lakhs):
    return int(lakhs * 100_000) * 100


def random_name(co_applicant_chance=0.25):
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    if random.random() < co_applicant_chance:
        name += f" & {random.choice(FIRST_NAMES)}"
    return name


def random_app_id():
    return "AP" + str(random.randint(1000000000, 9999999999))


def random_date(year_range=(2022, 2025)):
    y = random.randint(*year_range)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


def get_connection():
    return psycopg2.connect(
        host     = os.environ["DB_HOST"],
        port     = int(os.environ.get("DB_PORT", 5432)),
        dbname   = os.environ["DB_NAME"],
        user     = os.environ["DB_USER"],
        password = os.environ["DB_PASSWORD"],
    )


def main():
    conn = get_connection()
    cur  = conn.cursor()

    if DRY_RUN:
        print("DRY RUN — would wipe + re-insert the following:")
        print(f"  {len(LENDING_PARTNERS)} lending partners")
        print("  3 pinned test records (AP0020067658, 301047981, LAPSEC000007708)")
        print("  ~50 bulk random ops-pending records")
        conn.close()
        return

    # ── 1. Create tables if they don't exist (fresh DB on Kaggle) ────────────
    print("Creating tables if needed...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lending_partners (
            id                       BIGSERIAL PRIMARY KEY,
            name                     VARCHAR,
            slug                     VARCHAR,
            loan_account_number_regex VARCHAR DEFAULT '^[[:alnum:]]+$',
            inserted_at              TIMESTAMP NOT NULL,
            updated_at               TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS leads (
            id          BIGSERIAL PRIMARY KEY,
            name        VARCHAR,
            inserted_at TIMESTAMP NOT NULL,
            updated_at  TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS applications (
            id                  BIGSERIAL PRIMARY KEY,
            lead_id             BIGINT REFERENCES leads(id),
            lending_partner_id  BIGINT REFERENCES lending_partners(id),
            sanctioned_amount   BIGINT,
            branch_name         VARCHAR,
            bank_application_id VARCHAR,
            inserted_at         TIMESTAMP NOT NULL,
            updated_at          TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS disbursements (
            id                   BIGSERIAL PRIMARY KEY,
            application_id       BIGINT REFERENCES applications(id),
            loan_account_number  VARCHAR,
            disbursement_amount  BIGINT,
            disbursement_date    DATE,
            pending_approval_role VARCHAR,
            status               VARCHAR,
            inserted_at          TIMESTAMP NOT NULL,
            updated_at           TIMESTAMP NOT NULL
        );
    """)
    print("  done.")

    # ── 2. Wipe existing rows ─────────────────────────────────────────────────
    print("Wiping existing data...")
    cur.execute("DELETE FROM disbursements")
    cur.execute("DELETE FROM applications")
    cur.execute("DELETE FROM leads")
    cur.execute("DELETE FROM lending_partners")
    cur.execute("ALTER SEQUENCE lending_partners_id_seq RESTART WITH 1")
    cur.execute("ALTER SEQUENCE leads_id_seq RESTART WITH 1")
    cur.execute("ALTER SEQUENCE applications_id_seq RESTART WITH 1")
    cur.execute("ALTER SEQUENCE disbursements_id_seq RESTART WITH 1")
    print("  done.")

    # ── 3. Insert lending_partners ────────────────────────────────────────────
    print(f"Inserting {len(LENDING_PARTNERS)} lending partners...")
    lp_ids = {}  # name → id
    for name, slug, _lan_fn, regex in LENDING_PARTNERS:
        cur.execute("""
            INSERT INTO lending_partners (name, slug, loan_account_number_regex, inserted_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (name, slug.lower(), regex))
        lp_ids[name] = cur.fetchone()[0]
    print(f"  inserted ids: {list(lp_ids.values())}")

    # Helper: lan generator by lender name
    lp_lan_fn = {name: fn for name, _, fn, _ in LENDING_PARTNERS}

    # ── 4. Insert pinned test records ─────────────────────────────────────────
    print("Inserting pinned test records...")

    def insert_record(customer_name, lp_name, branch, sanction_paise, disb_paise, lan, app_id, disb_date, role="operations"):
        cur.execute("INSERT INTO leads (name, inserted_at, updated_at) VALUES (%s, NOW(), NOW()) RETURNING id", (customer_name,))
        lead_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO applications
                (lead_id, lending_partner_id, sanctioned_amount, branch_name, bank_application_id, inserted_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (lead_id, lp_ids[lp_name], sanction_paise, branch, app_id))
        app_id_db = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO disbursements
                (application_id, loan_account_number, disbursement_amount, disbursement_date,
                 pending_approval_role, status, inserted_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', NOW(), NOW())
            RETURNING id
        """, (app_id_db, lan, disb_paise, disb_date, role))
        disb_id = cur.fetchone()[0]
        return lead_id, app_id_db, disb_id

    # Test A — APPROVED: document matches DB exactly
    ids_a = insert_record(
        customer_name  = "Sathish Kumar & UMA",
        lp_name        = "Mahindra Finance",
        branch         = "MountRoad",
        sanction_paise = lakhs_to_paise(195),   # 1,950,000,000
        disb_paise     = lakhs_to_paise(195),   # 1,950,000,000
        lan            = "AP0020067658",
        app_id         = "AP0020067658",
        disb_date      = "2026-02-04",
    )
    print(f"  -> AP0020067658 (Sathish Kumar & UMA, 195L, Mahindra Finance) -- APPROVED test | disb_id={ids_a[2]}")

    # Test B — APPROVED: SUGUNA K Aadhar Housing Finance
    #   Sanction: ₹9,00,000 = 9L = 90,000,000 paise
    #   Disb:    ₹10,67,004 = 1,067,004 rupees = 106,700,400 paise
    ids_b = insert_record(
        customer_name  = "SUGUNA K",
        lp_name        = "Aadhar Housing Finance Limited",
        branch         = "Tambaram",
        sanction_paise = 90_000_000,    # 9L
        disb_paise     = 106_700_400,   # 10,67,004 rupees
        lan            = "301047981",
        app_id         = "301047891",
        disb_date      = "2026-03-14",
    )
    print(f"  -> 301047981 (SUGUNA K, 9L sanction, Aadhar Housing Finance) -- APPROVED test | disb_id={ids_b[2]}")

    # Test C — CHANGES REQUESTED: Zainab Medicals case (mirrors real CRM screen).
    #   The reviewer is processing case LAPSEC000007708 (Zainab Medicals, T.nagar, 63.5L).
    #   If they accidentally attach a different doc (e.g. Sathish Kumar sanctioned letter),
    #   every field will mismatch → verdict CHANGES REQUESTED.
    ids_c = insert_record(
        customer_name  = "Zainab Medicals",
        lp_name        = "Mahindra Finance",
        branch         = "T.Nagar",
        sanction_paise = lakhs_to_paise(63.5),   # 63,50,000
        disb_paise     = lakhs_to_paise(63.5),
        lan            = "LAPSEC000007708",
        app_id         = "91950",
        disb_date      = "2026-01-31",
    )
    print(f"  -> LAPSEC000007708 (Zainab Medicals, 63.5L, Mahindra Finance) -- mismatch test | disb_id={ids_c[2]}")

    # ── 5. Bulk random ops-pending records ────────────────────────────────────
    BULK_COUNT = 50
    print(f"Inserting {BULK_COUNT} bulk random ops-pending records...")
    lp_list = list(LENDING_PARTNERS)

    for i in range(BULK_COUNT):
        lp_name, _, lan_fn, _ = random.choice(lp_list)
        amount = lakhs_to_paise(random.choice(AMOUNT_LAKHS))
        disb_amount = int(amount * random.uniform(0.85, 1.0))  # disb ≤ sanction
        role = random.choice(["operations"] * 9 + ["sbi_operations"])

        insert_record(
            customer_name  = random_name(),
            lp_name        = lp_name,
            branch         = random.choice(BRANCHES),
            sanction_paise = amount,
            disb_paise     = disb_amount,
            lan            = lan_fn(),
            app_id         = random_app_id(),
            disb_date      = random_date(),
            role           = role,
        )
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{BULK_COUNT}...")

    conn.commit()
    cur.close()
    conn.close()

    total = 2 + BULK_COUNT
    print(f"\nDone. {total} records inserted.")
    print("\nVerify:")
    print("  python -c \"from db_lookup import lookup_by_lan; print(lookup_by_lan('AP0020067658'))\"")
    print("  python -c \"from db_lookup import lookup_by_lan; print(lookup_by_lan('301047981'))\"")


if __name__ == "__main__":
    main()
