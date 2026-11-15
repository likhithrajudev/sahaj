"""The database side of tenant isolation: the restricted role, the tenant column, the row-level security policies, and
the pool wrapper that sets the role and tenant on every connection it hands out."""
import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

import config
import tenancy

log = logging.getLogger("sahaj.tenancy")

# Tables holding one tenant's data. `shared` ones also show rows of the 'public' tenant (the platform's own knowledge
# base and default procedures) to every tenant, read-only.
TENANT_TABLES = ("users", "refresh_tokens", "user_memories", "user_files", "user_doc_chunks", "usage_events",
                 "reply_feedback", "cases", "case_messages", "episodes", "financial_events", "financial_inventory_items")
SHARED_TABLES = ("knowledge_chunks", "procedures")
PUBLIC = "public"

TENANTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id         TEXT PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,30}$'),
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    settings   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _role() -> str:
    role = config.DB_APP_ROLE
    if not re.fullmatch(r"[a-z_][a-z0-9_]{1,40}", role):
        raise ValueError("DB_APP_ROLE must be a plain lower-case identifier.")
    return role


class TenantPool:
    """Wraps the connection pool: every connection is set to the caller's tenant (and the restricted role) when it is
    handed out. Code keeps writing `async with pool.connection() as conn`; isolation comes with it."""

    def __init__(self, pool):
        self._pool = pool

    def __getattr__(self, name):   # close(), open() and the rest go to the real pool
        return getattr(self._pool, name)

    @asynccontextmanager
    async def connection(self, *args, **kwargs):
        async with self._pool.connection(*args, **kwargs) as conn:
            if tenancy.is_system():
                await conn.execute("SELECT set_config('role', 'none', false), set_config('app.tenant_id', '*', false)")
            else:
                await conn.execute("SELECT set_config('role', %s, false), set_config('app.tenant_id', %s, false)",
                                   (_role(), tenancy.get() or ""))
            yield conn


def _visible(shared: bool) -> str:
    me = "current_setting('app.tenant_id', true)"
    own = f"(tenant_id = {me} AND {me} <> '')" + (f" OR tenant_id = '{PUBLIC}'" if shared else "")
    return f"({own} OR {me} = '*')"


async def secure(pool) -> None:
    """Idempotent: the tenants table, the restricted role, a tenant column on every tenant table that exists, tenant-
    scoped uniqueness, row-level security policies, and the grants. Runs at startup and after each module creates its
    tables (tables that do not exist yet are skipped)."""
    role = _role()
    with tenancy.system():
        async with pool.connection() as conn:
            await conn.execute(TENANTS_SCHEMA)
            await conn.execute("INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                               (config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME))
            await conn.execute(f"""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN CREATE ROLE {role} NOLOGIN; END IF;
            END $$""")
            await conn.execute(f"GRANT {role} TO CURRENT_USER")
            for table in TENANT_TABLES + SHARED_TABLES:
                if (await (await conn.execute("SELECT to_regclass(%s)", (table,))).fetchone())[0] is None:
                    continue
                backfill = PUBLIC if table == "knowledge_chunks" else config.DEFAULT_TENANT
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT '{backfill}'")
                # From now on a row takes the tenant of whoever writes it; with no tenant set (unset, '' or the platform's
                # '*') the default is NULL and the write fails. The CHECK refuses anything that is not a real tenant id.
                await conn.execute(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET DEFAULT "
                                   "NULLIF(NULLIF(current_setting('app.tenant_id', true), ''), '*')")
                await conn.execute(f"DELETE FROM {table} WHERE tenant_id !~ '^[a-z0-9][a-z0-9-]{{1,30}}$'")   # nothing valid can be lost
                await conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_tenant_valid")
                await conn.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_tenant_valid CHECK (tenant_id ~ '^[a-z0-9][a-z0-9-]{{1,30}}$')")
                await conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_idx ON {table}(tenant_id)")
                visible = _visible(table in SHARED_TABLES)   # shared rows ('public') can be read by every tenant...
                own = _visible(False)                        # ...but only a tenant's own rows can be written, changed or deleted
                await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                for name in ("tenant_isolation", "tenant_read", "tenant_insert", "tenant_update", "tenant_delete"):
                    await conn.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
                await conn.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING {visible}")
                await conn.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK {own}")
                await conn.execute(f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING {own} WITH CHECK {own}")
                await conn.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING {own}")
            # A person's Google account, username and the knowledge base are unique per tenant, not globally.
            if (await (await conn.execute("SELECT to_regclass('users')")).fetchone())[0]:
                await conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_google_sub_key")
                await conn.execute("DROP INDEX IF EXISTS users_username_idx")
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_tenant_sub_idx ON users(tenant_id, google_sub)")
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_tenant_username_idx ON users(tenant_id, username)")
            if (await (await conn.execute("SELECT to_regclass('knowledge_chunks')")).fetchone())[0]:
                await conn.execute("ALTER TABLE knowledge_chunks DROP CONSTRAINT IF EXISTS knowledge_chunks_domain_doc_id_clause_key")
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS knowledge_chunks_tenant_key ON knowledge_chunks(tenant_id, domain, doc_id, clause)")
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
            await conn.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
            await conn.execute(f"REVOKE INSERT, UPDATE, DELETE ON tenants FROM {role}")   # tenants are managed by the platform only


async def tenant(pool, tenant_id: str) -> Optional[dict]:
    """The tenant's row (id, name, status, settings), or None."""
    from psycopg.rows import dict_row
    with tenancy.system():
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, name, status, settings, created_at FROM tenants WHERE id = %s", (tenant_id,))
            return await cur.fetchone()


async def create_tables(pool, sql: str) -> None:
    """Run a module's CREATE statements as the platform, then put its tables under tenant isolation."""
    with tenancy.system():
        async with pool.connection() as conn:
            await conn.execute(sql)
    await secure(pool)
