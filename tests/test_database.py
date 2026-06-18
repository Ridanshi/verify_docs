import pytest
import os
import tempfile
from database import init_db, save_result, get_recent_results


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_results.db"
    monkeypatch.setattr("database.DB_PATH", db_file)
    init_db()
    return db_file


def test_init_creates_table(tmp_db):
    import sqlite3
    with sqlite3.connect(tmp_db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='verifications'"
        ).fetchone()
    assert tables is not None


def test_save_and_retrieve(tmp_db):
    extracted = {"customer_name": "Zainab", "sanction_amount": "6350000"}
    expected = {"customer_name": "Zainab", "sanction_amount": "6350000"}
    save_result("doc.pdf", "APPROVED", extracted, expected, [])
    results = get_recent_results()
    assert len(results) == 1
    assert results[0]["status"] == "APPROVED"
    assert results[0]["filename"] == "doc.pdf"


def test_comments_stored(tmp_db):
    save_result("doc.jpg", "CHANGES_REQUESTED", {}, {}, ["Name mismatch", "Amount mismatch"])
    results = get_recent_results()
    assert "Name mismatch" in results[0]["comments"]


def test_multiple_saves_ordered_by_latest(tmp_db):
    save_result("a.pdf", "APPROVED", {}, {}, [])
    save_result("b.pdf", "CHANGES_REQUESTED", {}, {}, ["mismatch"])
    results = get_recent_results()
    assert results[0]["filename"] == "b.pdf"  # latest first


def test_limit_respected(tmp_db):
    for i in range(10):
        save_result(f"doc{i}.pdf", "APPROVED", {}, {}, [])
    results = get_recent_results(limit=3)
    assert len(results) == 3
