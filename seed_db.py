# seed_db.py — overwrites ops-pending staging records with realistic loan data.
#
# The cloned staging DB has garbage random values. This script replaces them
# with realistic Indian loan data so the DB Verify flow can be tested properly.
#
# Usage:
#   python seed_db.py          → seed all ops-pending records
#   python seed_db.py --dry-run → print what would be updated, don't write
#
# After running, 2 special test records are created:
#   LAN AP0020067658 → Sathish Kumar & UMA, 195L, Mahindra Finance  (APPROVED test)
#   LAN AP0020067659 → Zainab Medicals, 63.5L, Mahindra Finance     (CHANGES REQUESTED test)

import os
import sys
import random
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv

# ── Realistic seed data pools ────────────────────────────────────────────────

FIRST_NAMES = [
    "Rajesh", "Priya", "Amit", "Sunita", "Vikram", "Kavitha", "Suresh",
    "Anita", "Rahul", "Deepa", "Manoj", "Rekha", "Arun", "Meena", "Sanjay",
    "Lakshmi", "Ravi", "Geeta", "Prakash", "Shobha", "Harish", "Uma",
    "Ganesh", "Saritha", "Krishnan", "Padma", "Venkat", "Nirmala", "Ashok",
    "Jayanthi", "Mohan", "Sudha", "Bala", "Radha", "Ramesh", "Usha",
]

LAST_NAMES = [
    "Kumar", "Sharma", "Singh", "Reddy", "Nair", "Patel", "Rao", "Iyer",
    "Verma", "Gupta", "Joshi", "Mehta", "Shah", "Pillai", "Menon",
    "Agarwal", "Mishra", "Pandey", "Tiwari", "Yadav", "Bhat", "Shetty",
]

BANKS = [
    "Mahindra Finance", "HDFC Bank", "State Bank of India",
    "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank",
    "Bank of Baroda", "Punjab National Bank",
]

BRANCHES = [
    "T.Nagar", "MountRoad", "Anna Nagar", "Velachery", "Tambaram",
    "Andheri", "Bandra", "Powai", "Thane", "Pune Central",
    "Connaught Place", "Lajpat Nagar", "Dwarka", "Rohini",
    "Koramangala", "Indiranagar", "Whitefield", "Jayanagar",
    "Banjara Hills", "Jubilee Hills", "Hitech City",
    "Salt Lake", "Park Street", "Alipore",
    "Vashi", "Nerul", "Kharghar",
]

LOAN_TYPES = ["Home Loan", "LAP", "LAP Non Individual", "Plot Loan", "Construction Loan"]


def random_name(co_applicant_chance=0.3):
    """Generate a realistic Indian customer name, sometimes with co-applicant."""
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    if random.random() < co_applicant_chance:
        name += f" & {random.choice(FIRST_NAMES)}"
    return name


def random_lan(bank_name):
    """Generate a LAN in the correct format for the bank."""
    if "Mahindra" in bank_name:
        return "LAPSEC" + str(random.randint(100000000, 999999999))
    elif "HDFC" in bank_name:
        return "HL" + str(random.randint(1000000000, 9999999999))
    elif "SBI" in bank_name or "State Bank" in bank_name:
        return str(random.randint(10000000000, 99999999999))
    else:
        return "LAN" + str(random.randint(10000000, 99999999))


def random_amount_paise(min_lakhs=10, max_lakhs=500):
    """Random sanction/disbursement amount in paise."""
    lakhs = random.choice([
        10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 63.5,
        70, 75, 80, 90, 100, 120, 150, 175, 195, 200, 250, 300,
    ])
    lakhs = max(min_lakhs, min(max_lakhs, lakhs))
    rupees = int(lakhs * 100_000)
    return rupees * 100  # paise


def random_date():
    """Random disbursement date in the past 3 years."""
    year  = random.randint(2022, 2025)
    month = random.randint(1, 12)
    day   = random.randint(1, 28)
    return f"{year}-{month:02d}-{day:02d}"


def random_app_id():
    return "AP" + str(random.randint(1000000000, 9999999999))


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
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch all ops-pending disbursements with their join IDs
    cur.execute("""
        SELECT d.id AS disb_id, a.id AS app_id, l.id AS lead_id, lp.id AS lp_id
        FROM disbursements d
        JOIN applications    a  ON d.application_id    = a.id
        JOIN leads           l  ON a.lead_id           = l.id
        JOIN lending_partners lp ON a.lending_partner_id = lp.id
        WHERE d.pending_approval_role IN ('operations', 'sbi_operations')
        ORDER BY d.id
    """)
    records = cur.fetchall()
    print(f"Found {len(records)} ops-pending records to seed.")

    if DRY_RUN:
        print("DRY RUN — no changes written.")
        cur.close(); conn.close(); return

    cur2 = conn.cursor()

    for i, rec in enumerate(records):
        branch = random.choice(BRANCHES)
        name   = random_name()
        amount = random_amount_paise()
        date   = random_date()
        app_id = random_app_id()
        # Use existing lending_partner name to derive a realistic LAN format
        cur.execute("SELECT name FROM lending_partners WHERE id=%s", (rec["lp_id"],))
        lp_row  = cur.fetchone()
        bank    = lp_row["name"] if lp_row else "Unknown"
        lan     = random_lan(bank)

        # Don't touch lending_partners — unique name constraint prevents it
        cur2.execute("UPDATE leads             SET name=%s WHERE id=%s", (name,   rec["lead_id"]))
        cur2.execute("""
            UPDATE applications
            SET sanctioned_amount=%s, branch_name=%s, bank_application_id=%s
            WHERE id=%s
        """, (amount, branch, app_id, rec["app_id"]))
        cur2.execute("""
            UPDATE disbursements
            SET loan_account_number=%s, disbursement_amount=%s,
                disbursement_date=%s, updated_at=NOW()
            WHERE id=%s
        """, (lan, amount, date, rec["disb_id"]))

        if (i + 1) % 10 == 0:
            print(f"  seeded {i+1}/{len(records)}...")

    # ── Override 2 records for specific test scenarios ───────────────────────

    # Test A — APPROVED: DB matches the sample document exactly
    rec_a = records[0]
    cur2.execute("UPDATE leads SET name='Sathish Kumar & UMA' WHERE id=%s", (rec_a["lead_id"],))
    cur2.execute("""
        UPDATE applications
        SET sanctioned_amount=1950000000, branch_name='MountRoad',
            bank_application_id='AP0020067658'
        WHERE id=%s
    """, (rec_a["app_id"],))
    cur2.execute("""
        UPDATE disbursements
        SET loan_account_number='AP0020067658', disbursement_amount=1950000000,
            disbursement_date='2026-02-04', updated_at=NOW()
        WHERE id=%s
    """, (rec_a["disb_id"],))
    print("  → Set AP0020067658 (Sathish Kumar & UMA, 195L) — APPROVED test")

    # Test B — CHANGES REQUESTED: same doc but DB has different customer + amount
    rec_b = records[1]
    cur2.execute("UPDATE leads SET name='Zainab Medicals' WHERE id=%s", (rec_b["lead_id"],))
    cur2.execute("""
        UPDATE applications
        SET sanctioned_amount=635000000, branch_name='T.Nagar',
            bank_application_id='AP0020067659'
        WHERE id=%s
    """, (rec_b["app_id"],))
    cur2.execute("""
        UPDATE disbursements
        SET loan_account_number='AP0020067659', disbursement_amount=635000000,
            disbursement_date='2026-01-31', updated_at=NOW()
        WHERE id=%s
    """, (rec_b["disb_id"],))
    print("  → Set AP0020067659 (Zainab Medicals, 63.5L) — CHANGES REQUESTED test")

    conn.commit()
    cur2.close(); cur.close(); conn.close()
    print(f"\nDone. {len(records)} records seeded.")
    print("\nVerify with:")
    print("  python -c \"from db_lookup import lookup_by_lan; print(lookup_by_lan('AP0020067658'))\"")


if __name__ == "__main__":
    main()
