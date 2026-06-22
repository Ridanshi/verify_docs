# Database — saves every verification result to a local SQLite file (results.db).
#
# SQLite needs no server or setup — the file is created automatically on first run.
# Each row stores the document name, the verdict, what the model extracted,
# what was expected, and any mismatch comments.
#
# If the company later wants to move to PostgreSQL or MySQL, only the connection
# string in DB_PATH and the import need to change — everything else stays the same.

import sqlite3
import json
from datetime import datetime
from pathlib import Path

# results.db lives in the same folder as this file
DB_PATH = Path(__file__).parent / "results.db"


def init_db():
    """Create the verifications table if it doesn't already exist.

    Called once at app startup. Safe to call multiple times — the
    IF NOT EXISTS clause prevents it from wiping existing data.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      TEXT    NOT NULL,
                filename       TEXT,
                status         TEXT    NOT NULL,
                extracted_json TEXT    NOT NULL,
                expected_json  TEXT    NOT NULL,
                comments       TEXT    NOT NULL
            )
        """)


def save_result(filename: str, status: str, extracted: dict, expected: dict, comments: list[str]):
    """Save one verification result to the database.

    extracted and expected are stored as JSON strings so we can
    inspect the full field-by-field detail later if needed.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO verifications
               (timestamp, filename, status, extracted_json, expected_json, comments)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(timespec="seconds"),
                filename or "unknown",
                status,
                json.dumps(extracted),
                json.dumps(expected),
                "\n".join(comments),
            ),
        )


def get_recent_results(limit: int = 50) -> list[dict]:
    """Return the most recent verifications, newest first.

    Used by the History tab in the Gradio UI to show the last 50 checks.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row  # lets us access columns by name, not index
        rows = conn.execute(
            "SELECT id, timestamp, filename, status, comments FROM verifications "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
