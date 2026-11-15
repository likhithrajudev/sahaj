"""Procedural memory, administered per tenant: the prompts and workflows Sahaj runs with, as versions a tenant's admin
can publish, activate, roll back and reset. One tenant's versions never affect another (row-level security), and the
platform's own versions (tenant 'public') apply wherever a tenant has not set its own."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.deps import require_role
from auth.store import User
from memory import procedural

router = APIRouter(prefix="/admin/procedures", tags=["Procedural memory"])
admin = require_role("admin")


class Draft(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    note: Optional[str] = Field(None, max_length=500, description="Why this version: kept with it")


@router.get("")
async def list_procedures(_: User = Depends(admin)):
    """Every procedure, what it does, and which version this tenant runs: its own, the platform's, or the built-in default."""
    await procedural.refresh(force=True)
    running = procedural.versions()
    return [{"name": name, "description": desc, "running": running[name], "default": text}
            for name, (desc, text) in procedural.known().items()]


@router.get("/{name}")
async def versions(name: str, _: User = Depends(admin)):
    if name not in procedural.known():
        raise HTTPException(404, "No such procedure.")
    return {"name": name, "description": procedural.known()[name][0], "default": procedural.known()[name][1],
            "versions": await procedural.history(name)}


@router.post("/{name}", status_code=201)
async def publish(name: str, body: Draft, me: User = Depends(admin)):
    """A new draft version. Nothing changes until it is activated."""
    problem = procedural.validate(name, body.content)
    if problem:
        raise HTTPException(422 if name in procedural.known() else 404, problem)
    return {"name": name, **await procedural.publish(name, body.content, body.note, me.id)}


@router.post("/{name}/versions/{version}/activate")
async def activate(name: str, version: int, me: User = Depends(admin)):
    """Run with this version from now on (retires the previous one). Activating an older version is a rollback."""
    if name not in procedural.known():
        raise HTTPException(404, "No such procedure.")
    done = await procedural.activate(name, version, me.id)
    if done is None:
        raise HTTPException(404, "No such version for this tenant.")
    return done


@router.delete("/{name}/active")
async def reset(name: str, me: User = Depends(admin)):
    """Stop using this tenant's own version: back to the platform's, or the built-in default."""
    if name not in procedural.known():
        raise HTTPException(404, "No such procedure.")
    return {"name": name, "retired": await procedural.reset(name, me.id)}
