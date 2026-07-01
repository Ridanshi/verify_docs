# DB lookup module — connects to the company's PostgreSQL database and fetches
# expected field values for ops-pending disbursements.
#
# Auto-match flow:
#   1. VLM extracts loan_account_number from document
#   2. lookup_by_lan() queries disbursements where that LAN is pending ops review
#   3. Returns all expected field values as a dict (same shape as comparator expects)
#
# Safety rules enforced here:
#   - LAN must be non-empty and ≥5 chars before any DB query
#   - If no record found → raises LookupError (never returns empty dict)
#   - If multiple records found for same LAN → raises AmbiguousRecordError
#   - Caller must cross-check application_id after fetch (done in app.py)

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# Disbursements pending ops review. Both roles are included —
# 'operations' is the main ops queue, 'sbi_operations' is the SBI-specific queue.
_OPS_ROLES = ('operations', 'sbi_operations')

# Full lookup query: fetches all fields needed for comparison.
# Amounts are stored in paise (1 rupee = 100 paise) — divided by 100 here.
_LOOKUP_SQL = """
SELECT
    l.name                              AS customer_name,
    lp.name                             AS bank_name,
    a.bank_application_id               AS application_id,
    (a.sanctioned_amount  / 100.0)::bigint  AS sanction_amount,
    (d.disbursement_amount / 100.0)::bigint AS disbursement_amount,
    d.disbursement_date,
    a.branch_name                       AS branch,
    a.loan_type                         AS loan_type,
    d.loan_account_number,
    lp.loan_account_number_regex        AS lan_regex
FROM disbursements d
JOIN applications    a  ON d.application_id    = a.id
JOIN leads           l  ON a.lead_id           = l.id
JOIN lending_partners lp ON a.lending_partner_id = lp.id
WHERE d.loan_account_number    = %s
  AND d.pending_approval_role  IN %s
"""

# Queue query: all disbursements currently waiting for ops — shown in DB Verify tab
# so reviewer can pick from the list or confirm a match was found.
_QUEUE_SQL = """
SELECT
    d.loan_account_number,
    l.name                              AS customer_name,
    lp.name                             AS bank_name,
    a.branch_name                       AS branch,
    d.disbursement_date,
    (d.disbursement_amount / 100.0)::bigint AS disbursement_amount
FROM disbursements d
JOIN applications    a  ON d.application_id    = a.id
JOIN leads           l  ON a.lead_id           = l.id
JOIN lending_partners lp ON a.lending_partner_id = lp.id
WHERE d.pending_approval_role IN %s
ORDER BY d.inserted_at DESC
LIMIT 100
"""


class LookupError(Exception):
    """No ops-pending record found for the given LAN."""

class AmbiguousRecordError(Exception):
    """Multiple records found for the same LAN — cannot safely auto-match."""

class DBConnectionError(Exception):
    """Could not connect to PostgreSQL. Check .env and DB clone status."""


def _get_connection():
    """Open a PostgreSQL connection using credentials from .env."""
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing  = [k for k in required if not os.environ.get(k)]
    if missing:
        raise DBConnectionError(
            f"Missing environment variables: {', '.join(missing)}. "
            "Create a .env file — see .env.example."
        )
    try:
        return psycopg2.connect(
            host     = os.environ["DB_HOST"],
            port     = int(os.environ.get("DB_PORT", 5432)),
            dbname   = os.environ["DB_NAME"],
            user     = os.environ["DB_USER"],
            password = os.environ["DB_PASSWORD"],
            connect_timeout = 5,
        )
    except psycopg2.OperationalError as e:
        raise DBConnectionError(f"Cannot connect to database: {e}")


def _validate_lan(lan: str) -> None:
    """Reject obviously malformed LANs before hitting the DB."""
    if not lan or not lan.strip():
        raise ValueError("Loan Account Number is empty.")
    if len(lan.strip()) < 5:
        raise ValueError(f"Loan Account Number too short to be valid: '{lan}'")


def lookup_by_lan(lan: str) -> dict:
    """Fetch expected field values from DB for one ops-pending disbursement.

    Returns a dict with keys: customer_name, bank_name, application_id,
    sanction_amount, disbursement_amount, disbursement_date, branch,
    loan_account_number, lan_regex.

    Raises:
        ValueError          — LAN is malformed
        LookupError         — no matching ops-pending record found
        AmbiguousRecordError — multiple records matched (should not happen)
        DBConnectionError   — DB unreachable
    """
    _validate_lan(lan)
    lan = lan.strip()

    with _get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_LOOKUP_SQL, (lan, _OPS_ROLES))
            rows = cur.fetchall()

    if len(rows) == 0:
        raise LookupError(
            f"No ops-pending record found for LAN: '{lan}'. "
            "The document may have a mis-read LAN, or this case is not in the ops queue."
        )
    if len(rows) > 1:
        raise AmbiguousRecordError(
            f"Multiple ({len(rows)}) ops-pending records found for LAN: '{lan}'. "
            "Cannot safely auto-match. Please verify manually."
        )

    return dict(rows[0])


def fetch_ops_queue() -> list[dict]:
    """Return up to 100 disbursements currently pending ops verification.

    Used to populate the queue list in the DB Verify tab.
    Returns empty list if DB is unreachable (tab still loads, just shows empty queue).
    """
    try:
        with _get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(_QUEUE_SQL, (_OPS_ROLES,))
                return [dict(r) for r in cur.fetchall()]
    except DBConnectionError:
        return []
