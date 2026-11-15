"""Multi-tenant isolation. A tenant is an organisation Sahaj runs for (Paytm, or a bank, NBFC or insurer using it as a
white-label platform). Every person, conversation, file, memory, case and usage record belongs to exactly one tenant.

Isolation is enforced by Postgres itself (row-level security), not only by the queries we write:
  * each request runs as a restricted role (DB_APP_ROLE) with `app.tenant_id` set to the caller's tenant;
  * every tenant table has a policy that shows and accepts only rows of that tenant;
  * with no tenant set, nothing is visible and nothing can be written: a forgotten tenant fails closed.
Startup and background jobs that legitimately span tenants run in an explicit `system()` context."""
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")

current_tenant: ContextVar[Optional[str]] = ContextVar("current_tenant", default=None)
_system: ContextVar[bool] = ContextVar("tenancy_system", default=False)


class TenantError(Exception):
    pass


def valid(tenant_id: Optional[str]) -> bool:
    return bool(tenant_id and TENANT_ID.match(tenant_id))


def use(tenant_id: str) -> None:
    """Make `tenant_id` the tenant of everything that follows in this request, socket or task."""
    if not valid(tenant_id):
        raise TenantError(f"Invalid tenant id: {tenant_id!r}")
    current_tenant.set(tenant_id)
    _system.set(False)


def get() -> Optional[str]:
    return current_tenant.get()


def is_system() -> bool:
    return _system.get()


@contextmanager
def system():
    """Run as the platform, across tenants (schema setup, ingesting the shared knowledge base, background re-reads).
    Never use it to serve a person's request."""
    token = _system.set(True)
    try:
        yield
    finally:
        _system.reset(token)


@contextmanager
def as_tenant(tenant_id: str):
    """Run a block as one tenant (a background job working on that tenant's data)."""
    if not valid(tenant_id):
        raise TenantError(f"Invalid tenant id: {tenant_id!r}")
    t1, t2 = current_tenant.set(tenant_id), _system.set(False)
    try:
        yield
    finally:
        current_tenant.reset(t1)
        _system.reset(t2)
