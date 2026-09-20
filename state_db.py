import sqlite3
import time

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graded_submissions (
    submission_id TEXT PRIMARY KEY,
    doc_revision_id TEXT,
    graded_at REAL,
    recommended_grade REAL
);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def already_processed(submission_id: str, doc_revision_id: str) -> bool:
    """True if we've already produced a recommendation for this exact
    revision of the student's doc (i.e. nothing changed since last run)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT doc_revision_id FROM graded_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        return bool(row) and row[0] == doc_revision_id
    finally:
        conn.close()


def mark_processed(submission_id: str, doc_revision_id: str, recommended_grade: float):
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO graded_submissions (submission_id, doc_revision_id, graded_at, recommended_grade)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(submission_id) DO UPDATE SET
                 doc_revision_id=excluded.doc_revision_id,
                 graded_at=excluded.graded_at,
                 recommended_grade=excluded.recommended_grade""",
            (submission_id, doc_revision_id, time.time(), recommended_grade),
        )
        conn.commit()
    finally:
        conn.close()
