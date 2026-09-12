import sqlite3
import time

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graded_submissions (
    submission_id TEXT PRIMARY KEY,
    doc_revision_id TEXT,
    graded_at REAL,
    overall_score REAL,
    returned INTEGER DEFAULT 0
);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def already_graded(submission_id: str, doc_revision_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT doc_revision_id FROM graded_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        return bool(row) and row[0] == doc_revision_id


def mark_graded(submission_id: str, doc_revision_id: str, overall_score: float, returned: bool):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO graded_submissions (submission_id, doc_revision_id, graded_at, overall_score, returned)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(submission_id) DO UPDATE SET
                 doc_revision_id=excluded.doc_revision_id,
                 graded_at=excluded.graded_at,
                 overall_score=excluded.overall_score,
                 returned=excluded.returned""",
            (submission_id, doc_revision_id, time.time(), overall_score, int(returned)),
        )
        conn.commit()
