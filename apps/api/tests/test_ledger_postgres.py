import os
import sys
import threading
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from trust import ledger

DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


@pytest.fixture
def pg_ledger(monkeypatch):
    import psycopg
    schema = f"ledger_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    monkeypatch.setattr(config, "LEDGER_URL", f"{DB}{'&' if '?' in DB else '?'}options=-csearch_path%3D{schema}")
    monkeypatch.setattr(ledger, "_conn", None)
    yield
    if ledger._conn is not None:
        ledger._conn.conn.close()
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_postgres_ledger_chains_and_refuses_edits(pg_ledger):
    import psycopg
    first = ledger.append("consent", "user:1", {"purpose": "memory", "event": "granted"})
    second = ledger.append("audit", "session-1", {"steps": []}, trace_id="t1")
    assert second["seq"] > first["seq"] and ledger.verify() == {"intact": True, "entries": 2, "broken_at": None}
    assert [e["kind"] for e in ledger.entries(subject="user:1")] == ["consent"]
    assert ledger.entries(trace_id="t1")[0]["payload"] == {"steps": []}
    assert ledger.subjects("audit") == ["session-1"]
    for sql in ("UPDATE ledger SET payload = '{}'", "DELETE FROM ledger"):
        with pytest.raises(psycopg.errors.RaiseException):
            ledger._db().execute(sql)


def test_concurrent_appends_from_several_processes_keep_one_chain(pg_ledger):
    import subprocess
    script = (
        "import sys; sys.path.insert(0, '.'); import config; from trust import ledger; "
        "config.LEDGER_URL = sys.argv[1]; "
        "[ledger.append('audit', 'p' + sys.argv[2], {'i': i}) for i in range(15)]"
    )
    env = {**os.environ, "LANGSMITH_TRACING": "false"}
    procs = [subprocess.Popen([sys.executable, "-c", script, config.LEDGER_URL, str(n)],
                              cwd=Path(__file__).resolve().parent.parent, env=env) for n in range(3)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    result = ledger.verify()
    assert result["intact"] and result["entries"] == 45   # three processes, one unbroken chain
