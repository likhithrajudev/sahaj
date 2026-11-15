"""Append-only, hash-chained store for consent, audit and handoff records.

Each entry's hash covers the previous entry's hash, so editing or deleting any
row breaks the chain and `verify()` reports where. Triggers reject UPDATE/DELETE.
SQLite by default; Postgres when LEDGER_URL is set, which is what lets several API
processes (blue/green deploys) append safely: appends are serialised with an advisory lock.
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


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq        BIGSERIAL PRIMARY KEY,
    kind       TEXT NOT NULL,
    subject    TEXT NOT NULL,
    trace_id   TEXT,
    payload    TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_subject ON ledger(subject, kind);
CREATE INDEX IF NOT EXISTS ix_ledger_trace ON ledger(trace_id);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE p.proname = 'ledger_append_only' AND n.nspname = current_schema()) THEN
        CREATE FUNCTION ledger_append_only() RETURNS trigger AS $f$
            BEGIN RAISE EXCEPTION 'ledger is append-only'; END $f$ LANGUAGE plpgsql;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ledger_no_change' AND tgrelid = 'ledger'::regclass) THEN
        CREATE TRIGGER ledger_no_change BEFORE UPDATE OR DELETE ON ledger FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
    END IF;
END $$;
"""
APPEND_LOCK = 7_337_001   # pg_advisory_xact_lock key: one append at a time across every process


class _Postgres:
    def __init__(self, url: str):
        import psycopg
        self.url = url
        self.conn = psycopg.connect(url, autocommit=True)
        with self.conn.transaction():   # several processes may start at once: create the schema one at a time
            self.conn.execute("SELECT pg_advisory_xact_lock(%s)", (APPEND_LOCK,))
            self.conn.execute(PG_SCHEMA)

    def execute(self, sql: str, args=()):
        import psycopg
        try:
            return self.conn.execute(sql.replace("?", "%s"), args)
        except psycopg.OperationalError:   # a dropped connection: reconnect once
            self.conn = psycopg.connect(self.url, autocommit=True)
            return self.conn.execute(sql.replace("?", "%s"), args)


def _db():
    global _conn
    if _conn is None:
        if config.LEDGER_URL:
            _conn = _Postgres(config.LEDGER_URL)
        else:
            _conn = sqlite3.connect(config.LEDGER_DB, check_same_thread=False)
            _conn.executescript(SCHEMA)
    return _conn


def _digest(prev: str, kind: str, subject: str, trace_id: Optional[str], payload: str, ts: float) -> str:
    raw = "|".join([prev, kind, subject, trace_id or "", payload, repr(ts)])
    return hashlib.sha256(raw.encode()).hexdigest()


def append(kind: str, subject: str, payload: dict, trace_id: Optional[str] = None) -> dict:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    ts = time.time()
    insert = ("INSERT INTO ledger (kind, subject, trace_id, payload, created_at, prev_hash, hash) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)")
    with _lock:
        db = _db()
        if isinstance(db, _Postgres):
            with db.conn.transaction():
                db.execute("SELECT pg_advisory_xact_lock(?)", (APPEND_LOCK,))
                row = db.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
                prev = row[0] if row else GENESIS
                digest = _digest(prev, kind, subject, trace_id, body, ts)
                seq = db.execute(insert + " RETURNING seq", (kind, subject, trace_id, body, ts, prev, digest)).fetchone()[0]
            return {"seq": seq, "hash": digest}
        row = db.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        digest = _digest(prev, kind, subject, trace_id, body, ts)
        cur = db.execute(insert, (kind, subject, trace_id, body, ts, prev, digest))
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
