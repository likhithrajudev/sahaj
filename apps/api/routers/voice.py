import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config
from auth.deps import websocket_user
from gateway.middleware import client_ip
from observability import metrics
from orchestrator.session import Session

router = APIRouter(tags=["Voice"])

UNAUTHORIZED = 4401  # WebSocket close code: the access token is missing, invalid or expired


@router.websocket("/ws/voice")
async def voice(ws: WebSocket):
    """Needs an access token: `Authorization: Bearer <token>` or `?access_token=<token>`. `?resume=<session id>` carries
    on a conversation from working memory after a dropped connection."""
    user = await websocket_user(ws)
    await ws.accept()
    if user is None:
        return await ws.close(code=UNAUTHORIZED, reason="Sign in first.")
    session = Session(ws, user, client_ip(ws.scope), resume=ws.query_params.get("resume"))
    metrics.WS_CONNECTIONS.inc()
    try:
        await session.start()
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await session.on_audio(msg["bytes"])
            elif msg.get("text"):
                await session.on_control(msg["text"])
    except WebSocketDisconnect:
        pass
    finally:
        metrics.WS_CONNECTIONS.dec()
        await session.close()


@router.websocket("/ws/voice/stream")
async def voice_stream(ws: WebSocket):
    """Accept audio chunks while a client microphone stays active; clients mark each speech segment with audio_end."""
    user = await websocket_user(ws)
    await ws.accept()
    if user is None:
        return await ws.close(code=UNAUTHORIZED, reason="Sign in first.")
    session = Session(ws, user, client_ip(ws.scope), resume=ws.query_params.get("resume"))
    metrics.WS_CONNECTIONS.inc()
    audio = bytearray()
    discard_audio = False
    try:
        await session.start()
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if discard_audio:
                    continue
                if len(audio) + len(msg["bytes"]) > config.MAX_UPLOAD_BYTES:
                    audio.clear()
                    discard_audio = True
                    await session._error("That audio segment is too large. Start a shorter segment.")
                else:
                    audio.extend(msg["bytes"])
                continue
            raw = msg.get("text")
            if not raw:
                continue
            try:
                control = json.loads(raw)
            except (ValueError, TypeError):
                await session._error("Expected a JSON control message.")
                continue
            if control.get("type") == "audio_end":
                if discard_audio:
                    discard_audio = False
                    audio.clear()
                    continue
                if audio:
                    segment = bytes(audio)
                    audio.clear()
                    await session.on_audio(segment)
                else:
                    await session._error("No audio was received for that segment.")
            elif control.get("type") == "audio_cancel":
                audio.clear()
                discard_audio = False
                await ws.send_json({"type": "audio_cancelled"})
            else:
                await session.on_control(raw)
    except WebSocketDisconnect:
        pass
    finally:
        metrics.WS_CONNECTIONS.dec()
        await session.close()
