# seed_db_eval.py — wipe DB and re-seed from synthetic/ground_truth.json.
#
# For each unique LAN in ground_truth.json, inserts one DB record (lead,
# application, disbursement) with the EXPECTED values from the synthetic
# generator. Used to evaluate the DB Verify pipeline end-to-end: the same
# ground truth that the generator labelled the documents against is now the
# DB's view of reality.
#
# PDF and JPG of the same doc share a LAN — inserted once.
#
# Usage:
#   python seed_db_eval.py            → wipe + re-seed from ground_truth.json
#   python seed_db_eval.py --dry-run  → print plan, no writes

import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv
GROUND_TRUTH = Path("synthetic/ground_truth.json")

# Lender names in ground_truth.json must map exactly to these — keep aligned.
LENDING_PARTNERS = [
    ("Mahindra Finance",               "lapsec", r"^LAPSEC\d{9}$"),
    ("Aadhar Housing Finance Limited", "ahfl",   r"^\d{9}$"),
    ("HDFC Bank",                      "hl",     r"^HL\d{10}$"),
]


def get_connection():
    return psycopg2.connect(
        host     = os.environ["DB_HOST"],
        port     = int(os.environ.get("DB_PORT", 5432)),
        dbname   = os.environ["DB_NAME"],
        user     = os.environ["DB_USER"],
        password = os.environ["DB_PASSWORD"],
    )


def main():
    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    # Deduplicate by LAN — pdf and jpg of same doc share a LAN.
    unique_cases = {}
    for filename, entry in gt.items():
        ev  = entry["expected_values"]
        lan = ev["loan_account_number"]
        if lan not in unique_cases:
            unique_cases[lan] = ev

    print(f"Loaded {len(gt)} entries from ground_truth.json")
    print(f"Unique LANs (cases to seed): {len(unique_cases)}")

    if DRY_RUN:
        for lan, ev in list(unique_cases.items())[:5]:
            print(f"  {lan} | {ev['customer_name']} | {ev['bank_name']} | {ev['branch']}")
        print(f"  ... and {len(unique_cases) - 5} more")
        return

    conn = get_connection()
    cur  = conn.cursor()

    # ── 1. Create tables (idempotent) ───────────────────────────────────────
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

    # ── 2. Wipe ─────────────────────────────────────────────────────────────
    print("Wiping existing data...")
    cur.execute("DELETE FROM disbursements")
    cur.execute("DELETE FROM applications")
    cur.execute("DELETE FROM leads")
    cur.execute("DELETE FROM lending_partners")
    for seq in ("lending_partners_id_seq", "leads_id_seq", "applications_id_seq", "disbursements_id_seq"):
        cur.execute(f"ALTER SEQUENCE {seq} RESTART WITH 1")

    # ── 3. Insert lending partners ──────────────────────────────────────────
    lp_ids = {}
    for name, slug, regex in LENDING_PARTNERS:
        cur.execute(
            """INSERT INTO lending_partners (name, slug, loan_account_number_regex, inserted_at, updated_at)
               VALUES (%s, %s, %s, NOW(), NOW()) RETURNING id""",
            (name, slug, regex),
        )
        lp_ids[name] = cur.fetchone()[0]
    print(f"Inserted {len(lp_ids)} lending partners.")

    # ── 4. Insert one record per unique LAN ─────────────────────────────────
    inserted = 0
    skipped  = 0
    for lan, ev in unique_cases.items():
        bank = ev["bank_name"]
        if bank not in lp_ids:
            skipped += 1
            continue

        # rupees → paise (×100). ground_truth.sanction_amount is already in rupees.
        sanction_paise = int(ev["sanction_amount"]) * 100 if ev.get("sanction_amount") else None
        disb_paise     = int(ev["disbursement_amount"]) * 100 if ev.get("disbursement_amount") else None

        cur.execute("INSERT INTO leads (name, inserted_at, updated_at) VALUES (%s, NOW(), NOW()) RETURNING id",
                    (ev["customer_name"],))
        lead_id = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO applications
               (lead_id, lending_partner_id, sanctioned_amount, branch_name, bank_application_id, inserted_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, NOW(), NOW()) RETURNING id""",
            (lead_id, lp_ids[bank], sanction_paise, ev["branch"], ev["application_id"]),
        )
        app_id_db = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO disbursements
               (application_id, loan_account_number, disbursement_amount, disbursement_date,
                pending_approval_role, status, inserted_at, updated_at)
               VALUES (%s, %s, %s, %s, 'operations', 'pending', NOW(), NOW())""",
            (app_id_db, lan, disb_paise, ev["disbursement_date"]),
        )
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone. {inserted} cases inserted, {skipped} skipped (unknown lender).")
    print("Verify with:")
    print("  python -c \"from db_lookup import lookup_by_lan; print(lookup_by_lan('LAPSEC954654015'))\"")


if __name__ == "__main__":
    main()
