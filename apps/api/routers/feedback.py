from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import feedback
from auth.deps import current_user, require_role
from auth.store import User
from observability.metrics import FEEDBACK
from trust import ledger
from trust.pii import Vault, normalise_digits

router = APIRouter(tags=["Feedback"])


class FeedbackIn(BaseModel):
    trace_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", description="From the reply's `trace_id`")
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(None, max_length=500)


@router.post("/feedback", status_code=204)
async def rate(body: FeedbackIn, user: User = Depends(current_user)):
    """Rate a reply. Rating the same reply again replaces the earlier rating. A comment is stored with personal
    identifiers masked."""
    if not ledger.entries(trace_id=body.trace_id, kind="audit"):
        raise HTTPException(404, "No such reply.")
    comment = Vault().mask(normalise_digits(body.comment.strip())) if body.comment and body.comment.strip() else None
    await feedback.save(user.id, body.trace_id, body.rating, comment)
    FEEDBACK.labels(body.rating).inc()


@router.get("/admin/feedback")
async def review(rating: Optional[Literal["up", "down"]] = None, limit: int = Query(50, ge=1, le=200),
                 _: User = Depends(require_role("admin"))):
    """Counts and the latest ratings. Each carries the `trace_id`: open /audit/trace/{id} to see exactly what happened."""
    return await feedback.summary(rating, limit)
