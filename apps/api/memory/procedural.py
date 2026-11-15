"""Layer 4 - procedural memory: HOW Sahaj works, as versioned data rather than code: the answer rules, the intent
classifier's instructions, the fine-print instructions and the fine-print checklists.

Every procedure has a built-in default (the text in the code). A tenant can publish its own versions; one version per
procedure is active. Platform-wide versions live under the 'public' tenant and apply to every tenant that has not set
its own. Every activation is recorded in the audit ledger, every turn's trace records the versions it ran with, and an
earlier version can be re-activated at any time (a rollback).

`text(name)` is synchronous and reads a per-tenant cache; `refresh()` reloads it (each turn calls it; it only touches
the database when the cache is older than PROCEDURES_CACHE_SECONDS)."""
import time
from typing import Dict, Optional, Tuple

from psycopg.rows import dict_row

import config
import tenancy
from auth.store import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS procedures (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT NOT NULL,                -- isolation and its default come from tenancy/db.py
    name         TEXT NOT NULL,
    version      INT NOT NULL,
    content      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
    note         TEXT,
    created_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS procedures_version_idx ON procedures(tenant_id, name, version);
CREATE UNIQUE INDEX IF NOT EXISTS procedures_active_idx ON procedures(tenant_id, name) WHERE status = 'active';
"""


def _defaults() -> Dict[str, Tuple[str, str]]:
    """name -> (what it is, the built-in text)."""
    from agents.base import CORE, FINE_PRINT
    from orchestrator.prompts import CLASSIFIER_SYSTEM, FINE_PRINT_CHECKLISTS
    return {
        "answer.core_rules": ("The rules every answer follows (grounding, citations, tone).", CORE),
        "intent.classifier": ("Instructions for classifying what the person wants.", CLASSIFIER_SYSTEM),
        "answer.fine_print": ("How to present the hidden terms and costs of a plan or loan.", FINE_PRINT),
        "fine_print.checklist.insurance": ("Insurance topics checked for hidden terms, one per line.", FINE_PRINT_CHECKLISTS["insurance"]),
        "fine_print.checklist.loan": ("Loan topics checked for hidden costs, one per line.", FINE_PRINT_CHECKLISTS["loan"]),
    }


def known() -> Dict[str, Tuple[str, str]]:
    return _defaults()


_cache: Dict[str, Tuple[float, Dict[str, Tuple[str, int, str]]]] = {}   # tenant -> (loaded at, name -> (scope, version, text))


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


def invalidate(tenant: Optional[str] = None) -> None:
    if tenant:
        _cache.pop(tenant, None)
    else:
        _cache.clear()


async def refresh(force: bool = False) -> None:
    """Load the active versions for the current tenant (its own first, then the platform's)."""
    tenant = tenancy.get()
    if not tenant:
        return
    hit = _cache.get(tenant)
    if hit and not force and time.monotonic() - hit[0] < config.PROCEDURES_CACHE_SECONDS:
        return
    try:
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT tenant_id, name, version, content FROM procedures WHERE status = 'active'")
            rows = await cur.fetchall()
    except Exception:
        rows = []   # no database: the built-in defaults are always there
    active: Dict[str, Tuple[str, int, str]] = {}
    for r in sorted(rows, key=lambda r: r["tenant_id"] != "public"):   # public first, so the tenant's own overrides it
        active[r["name"]] = ("tenant" if r["tenant_id"] != "public" else "platform", r["version"], r["content"])
    _cache[tenant] = (time.monotonic(), active)


def text(name: str) -> str:
    """The active text of a procedure for the current tenant, or its built-in default."""
    tenant = tenancy.get()
    found = _cache.get(tenant, (0, {}))[1].get(name) if tenant else None
    return found[2] if found else _defaults()[name][1]


def versions() -> Dict[str, str]:
    """Which version of each procedure this turn runs with, for the trace: 'default', 'tenant:v3' or 'platform:v2'."""
    tenant = tenancy.get()
    active = _cache.get(tenant, (0, {}))[1] if tenant else {}
    return {name: (f"{active[name][0]}:v{active[name][1]}" if name in active else "default") for name in _defaults()}


def validate(name: str, content: str) -> Optional[str]:
    """Why this text cannot be a version of `name`, or None. Guards against publishing something that would break a turn."""
    if name not in _defaults():
        return "Unknown procedure."
    if not 20 <= len(content) <= 20000:
        return "Content must be 20 to 20,000 characters."
    if name == "intent.classifier" and not all(k in content for k in ('"intent"', '"confidence"', '"search"')):
        return 'The classifier must still ask for the "intent", "confidence" and "search" keys.'
    if name.startswith("fine_print.checklist.") and not 3 <= len([l for l in content.splitlines() if l.strip()]) <= 15:
        return "A checklist needs 3 to 15 topics, one per line."
    if name == "answer.core_rules" and "tag" not in content:
        return "The core rules must keep the source-tag (citation) rule."
    return None


async def history(name: str) -> list:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT tenant_id, version, status, note, created_by, created_at, activated_at, content FROM procedures
                             WHERE name = %s ORDER BY tenant_id, version DESC""", (name,))
        return [{**r, "created_by": str(r["created_by"]) if r["created_by"] else None,
                 "scope": "platform" if r.pop("tenant_id") == "public" else "tenant"} for r in await cur.fetchall()]


async def publish(name: str, content: str, note: Optional[str], author: Optional[str]) -> dict:
    """A new draft version for the current tenant (not used until activated)."""
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""INSERT INTO procedures (name, version, content, note, created_by)
                             VALUES (%(n)s, COALESCE((SELECT max(version) FROM procedures WHERE name = %(n)s
                                                      AND tenant_id = current_setting('app.tenant_id')), 0) + 1, %(c)s, %(note)s, %(a)s)
                             RETURNING version, status, created_at""", {"n": name, "c": content, "note": note, "a": author})
        return await cur.fetchone()


async def activate(name: str, version: int, author: Optional[str]) -> Optional[dict]:
    """Make `version` the tenant's active one (retiring the previous). Also how a rollback is done. Audited."""
    from trust import ledger
    async with db().connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT 1 FROM procedures WHERE name = %s AND version = %s AND tenant_id = current_setting('app.tenant_id')",
                                     (name, version))
            if await cur.fetchone() is None:
                return None
            await conn.execute("UPDATE procedures SET status = 'retired' WHERE name = %s AND status = 'active' "
                               "AND tenant_id = current_setting('app.tenant_id')", (name,))
            await conn.execute("UPDATE procedures SET status = 'active', activated_at = now() WHERE name = %s AND version = %s "
                               "AND tenant_id = current_setting('app.tenant_id')", (name, version))
    ledger.append("procedure", f"tenant:{tenancy.get()}", {"event": "activated", "name": name, "version": version, "actor": author})
    invalidate(tenancy.get())
    return {"name": name, "version": version, "status": "active"}


async def reset(name: str, author: Optional[str]) -> int:
    """Stop using the tenant's own version: back to the platform's, or the built-in default."""
    from trust import ledger
    async with db().connection() as conn:
        n = (await conn.execute("UPDATE procedures SET status = 'retired' WHERE name = %s AND status = 'active' "
                                "AND tenant_id = current_setting('app.tenant_id')", (name,))).rowcount
    ledger.append("procedure", f"tenant:{tenancy.get()}", {"event": "reset_to_default", "name": name, "actor": author})
    invalidate(tenancy.get())
    return n
