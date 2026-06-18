import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "results.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                filename  TEXT,
                status    TEXT    NOT NULL,
                extracted_json TEXT NOT NULL,
                expected_json  TEXT NOT NULL,
                comments  TEXT    NOT NULL
            )
        """)


def save_result(filename: str, status: str, extracted: dict, expected: dict, comments: list[str]):
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, timestamp, filename, status, comments FROM verifications "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
