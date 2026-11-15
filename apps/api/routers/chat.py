import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth.deps import current_user
from auth.store import User
from orchestrator import registry

log = logging.getLogger("sahaj.chat")
router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Omit to start a conversation; send the id from its `session` event to continue it")
    message: dict = Field(description='A client message exactly as on the WebSocket: {"type":"text","text":"..."}, '
                                      '{"type":"consent","purpose":"conversation","granted":true} or {"type":"handoff"}')


@router.post("/stream", responses={200: {"content": {"text/event-stream": {}}}})
async def stream(body: ChatRequest, user: User = Depends(current_user)):
    """The voice protocol over HTTP for text clients. The response is a Server-Sent Events stream: each `data:` line
    is one of the WebSocket's JSON events (`session`, `consent_required`, `status`, `user`, `card`, `assistant`, `done`,
    `handoff`, `error`), and the stream ends when the turn is finished. No audio is sent.

    The reply text arrives whole, after the guardrails have passed it; `status` events show progress meanwhile."""
    await registry.sweep()
    entry, created = registry.acquire(user, body.session_id)
    if entry is None:
        raise HTTPException(404, "No such conversation. It may have expired: start a new one without session_id.")
    queue: asyncio.Queue = asyncio.Queue()

    async def run():
        async with entry.lock:
            entry.session.ws = registry.QueueSocket(queue)
            try:
                if created:
                    await entry.session.start(ask_consent=False)  # a message that needs consent asks for it itself
                await entry.session.on_control(json.dumps(body.message))
            except Exception:  # whatever went wrong, the client must get an ending rather than a hung stream
                log.exception("Chat turn failed")
                await queue.put({"type": "error", "message": "Something went wrong. Please try again."})
            finally:
                await queue.put(None)

    task = asyncio.create_task(run())

    async def events():
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():  # the client went away mid-turn
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.delete("/{session_id}", status_code=204)
async def end(session_id: str, user: User = Depends(current_user)):
    """End a conversation now. Memory is saved if the person allows it."""
    if not await registry.end(user, session_id):
        raise HTTPException(404, "No such conversation.")
    return Response(status_code=204)
