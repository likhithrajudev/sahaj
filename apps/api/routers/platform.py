"""Platform administration: the organisations (tenants) Sahaj runs for. Protected by the platform's X-Admin-Key, not by a
tenant's own admins: a tenant admin can never create, see or change another tenant."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

import tenancy
from auth.store import db
from routers.audit import require_admin

router = APIRouter(prefix="/platform", tags=["Platform"], dependencies=[Depends(require_admin)])


class TenantIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,30}$", description="Short id sent by the partner's app as X-Tenant-ID")
    name: str = Field(min_length=1, max_length=100)
    settings: dict = Field(default_factory=dict, description='For example {"budget_usd": 10} for this tenant\'s default monthly limit')


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[Literal["active", "suspended"]] = None
    settings: Optional[dict] = None


@router.get("/tenants")
async def list_tenants():
    with tenancy.system():
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""SELECT t.id, t.name, t.status, t.settings, t.created_at,
                                        (SELECT count(*) FROM users u WHERE u.tenant_id = t.id) AS users
                                 FROM tenants t ORDER BY t.created_at""")
            return await cur.fetchall()


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantIn):
    with tenancy.system():
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("INSERT INTO tenants (id, name, settings) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING *",
                              (body.id, body.name, Jsonb(body.settings)))
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(409, "A tenant with that id already exists.")
    return row


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate):
    """Suspending a tenant stops new sign-ins for it at once; its data is kept."""
    fields = {k: (Jsonb(v) if k == "settings" else v) for k, v in body.model_dump(exclude_none=True).items()}
    if not fields:
        raise HTTPException(400, "Nothing to change.")
    sets = ", ".join(f"{k} = %({k})s" for k in fields)   # keys come from the model above, never from input
    with tenancy.system():
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"UPDATE tenants SET {sets} WHERE id = %(id)s RETURNING *", {**fields, "id": tenant_id})
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, "No such tenant.")
    return row
