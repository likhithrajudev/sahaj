"""Append-only, hash-chained store for consent, audit and handoff records.

Each entry's hash covers the previous entry's hash, so editing or deleting any
row breaks the chain and `verify()` reports where. SQLite triggers also reject
UPDATE/DELETE. For production, move to Postgres and anchor the head hash somewhere
outside this database (someone with file access could rewrite the whole chain).
"""
import hashlib
import json
import sqlite3
import threading
import time
from typing import List, Optional

import config

GENESIS = "0" * 64
_lock = threading.Lock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    subject    TEXT NOT NULL,
    trace_id   TEXT,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_subject ON ledger(subject, kind);
CREATE INDEX IF NOT EXISTS ix_ledger_trace ON ledger(trace_id);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
    BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
    BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


def _db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.LEDGER_DB, check_same_thread=False)
        _conn.executescript(SCHEMA)
    return _conn


def _digest(prev: str, kind: str, subject: str, trace_id: Optional[str], payload: str, ts: float) -> str:
    raw = "|".join([prev, kind, subject, trace_id or "", payload, repr(ts)])
    return hashlib.sha256(raw.encode()).hexdigest()


def append(kind: str, subject: str, payload: dict, trace_id: Optional[str] = None) -> dict:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    ts = time.time()
    with _lock:
        db = _db()
        row = db.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        digest = _digest(prev, kind, subject, trace_id, body, ts)
        cur = db.execute(
            "INSERT INTO ledger (kind, subject, trace_id, payload, created_at, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, subject, trace_id, body, ts, prev, digest),
        )
        db.commit()
    return {"seq": cur.lastrowid, "hash": digest}


def entries(subject: Optional[str] = None, kind: Optional[str] = None, trace_id: Optional[str] = None) -> List[dict]:
    where, args = [], []
    for column, value in (("subject", subject), ("kind", kind), ("trace_id", trace_id)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    sql = "SELECT seq, kind, subject, trace_id, payload, created_at, hash FROM ledger"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = _db().execute(sql + " ORDER BY seq", args).fetchall()
    return [
        {"seq": s, "kind": k, "subject": sub, "trace_id": t, "payload": json.loads(p), "created_at": c, "hash": h}
        for s, k, sub, t, p, c, h in rows
    ]


def subjects(kind: str = "audit", limit: int = 50) -> List[str]:
    """The most recently active sessions, newest first."""
    rows = _db().execute("SELECT subject FROM ledger WHERE kind = ? GROUP BY subject ORDER BY MAX(seq) DESC LIMIT ?",
                         (kind, limit)).fetchall()
    return [r[0] for r in rows]


def verify() -> dict:
    """Recompute the whole chain. `broken_at` is the first bad seq, or None."""
    prev = GENESIS
    rows = _db().execute(
        "SELECT seq, kind, subject, trace_id, payload, created_at, prev_hash, hash FROM ledger ORDER BY seq"
    ).fetchall()
    for seq, kind, subject, trace_id, payload, ts, prev_hash, digest in rows:
        if prev_hash != prev or _digest(prev, kind, subject, trace_id, payload, ts) != digest:
            return {"intact": False, "entries": len(rows), "broken_at": seq}
        prev = digest
    return {"intact": True, "entries": len(rows), "broken_at": None}
