import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth.deps import current_user, require_role
from auth.store import User
from desk import live
from marketing import store as campaigns
from observability.metrics import MARKETING_EVENTS
from storage import blob, files
from trust import consent

router = APIRouter(tags=["Marketing"])
admin = require_role("admin")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_IMAGE = 5 * 1024 * 1024


class Audience(BaseModel):
    languages: Optional[List[str]] = None
    platforms: Optional[List[Literal["web", "android", "ios"]]] = None


class CampaignIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=500)
    cta_label: Optional[str] = Field(None, max_length=30)
    cta_url: Optional[str] = Field(None, max_length=500, pattern=r"^https://")
    audience: Audience = Audience()


def _card(c: dict) -> dict:
    keep = ("id", "title", "body", "cta_label", "cta_url", "audience", "status", "created_at", "sent_at", "recipients",
            "skipped_cap", "seen", "clicked")
    return {**{k: c.get(k) for k in keep}, "has_image": bool(c.get("image_blob"))}


@router.post("/admin/campaigns", status_code=201)
async def create(body: CampaignIn, me: User = Depends(admin)):
    return _card(await campaigns.create({**body.model_dump(), "audience": body.audience.model_dump(exclude_none=True)}, me.id))


@router.get("/admin/campaigns")
async def list_campaigns(_: User = Depends(admin)):
    return [_card(c) for c in await campaigns.list_all()]


@router.get("/admin/campaigns/{campaign_id}")
async def detail(campaign_id: str, _: User = Depends(admin)):
    c = await campaigns.get(campaign_id)
    if c is None:
        raise HTTPException(404, "No such campaign.")
    return {**_card(c), "audience_size": len(await campaigns.audience(c)) if c["status"] == "draft" else None}


@router.post("/admin/campaigns/{campaign_id}/image")
async def upload_image(campaign_id: str, file: UploadFile, me: User = Depends(admin)):
    c = await campaigns.get(campaign_id)
    if c is None or c["status"] != "draft":
        raise HTTPException(404 if c is None else 409, "No such draft campaign.")
    data = await file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "Images can be up to 5 MB.")
    kind = files.sniff(data)
    if not kind or kind[0] not in IMAGE_TYPES:
        raise HTTPException(415, "Upload a PNG, JPEG or WebP image.")
    name = f"{me.tenant_id}/_marketing/{campaign_id}/{uuid.uuid4().hex}.{kind[2]}"
    await blob.get().put(name, data, kind[0])
    await campaigns.set_image(campaign_id, name, kind[0])
    return _card(await campaigns.get(campaign_id))


@router.post("/admin/campaigns/{campaign_id}/send")
async def send(campaign_id: str, me: User = Depends(admin)):
    """Send now to everyone in this tenant who opted in to marketing (and matches the audience)."""
    sent = await campaigns.send(campaign_id, me.id)
    if sent is None:
        raise HTTPException(409, "Only a draft campaign can be sent.")
    MARKETING_EVENTS.labels("delivered").inc(sent["recipients"])
    item = {"title": sent["title"], "body": sent["body"], "cta_label": sent["cta_label"], "has_image": bool(sent.get("image_blob"))}
    for user_id in sent["user_ids"]:
        await live.to_customer(user_id, {"type": "inbox", "item": item})
    return _card(sent)


@router.post("/admin/campaigns/{campaign_id}/cancel")
async def cancel(campaign_id: str, _: User = Depends(admin)):
    if not await campaigns.cancel(campaign_id):
        raise HTTPException(409, "Only a draft campaign can be cancelled.")
    return {"id": campaign_id, "status": "cancelled"}


@router.get("/inbox")
async def my_inbox(user: User = Depends(current_user)):
    return {"marketing_consent": consent.is_active(user.subject, "marketing"), "items": await campaigns.inbox(user.id)}


async def _mine(user: User, delivery_id: str) -> dict:
    d = await campaigns.delivery(user.id, delivery_id)
    if d is None:
        raise HTTPException(404, "No such message.")
    return d


@router.post("/inbox/{delivery_id}/seen", status_code=204)
async def seen(delivery_id: str, user: User = Depends(current_user)):
    await _mine(user, delivery_id)
    await campaigns.mark(user.id, delivery_id, "seen_at")
    MARKETING_EVENTS.labels("seen").inc()
    return Response(status_code=204)


@router.post("/inbox/{delivery_id}/click")
async def click(delivery_id: str, user: User = Depends(current_user)):
    d = await _mine(user, delivery_id)
    await campaigns.mark(user.id, delivery_id, "clicked_at")
    MARKETING_EVENTS.labels("clicked").inc()
    return {"url": d["cta_url"]}


@router.delete("/inbox/{delivery_id}", status_code=204)
async def dismiss(delivery_id: str, user: User = Depends(current_user)):
    await _mine(user, delivery_id)
    await campaigns.mark(user.id, delivery_id, "dismissed_at")
    return Response(status_code=204)


@router.get("/inbox/{delivery_id}/image")
async def image(delivery_id: str, user: User = Depends(current_user)):
    d = await _mine(user, delivery_id)
    if not d["image_blob"]:
        raise HTTPException(404, "No image.")
    return StreamingResponse(blob.get().stream(d["image_blob"]), media_type=d["image_type"],
                             headers={"Cache-Control": "private, max-age=3600"})
