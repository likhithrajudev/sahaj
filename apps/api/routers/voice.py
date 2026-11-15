from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth.deps import websocket_user
from orchestrator.session import Session

router = APIRouter(tags=["Voice"])

UNAUTHORIZED = 4401  # WebSocket close code: the access token is missing, invalid or expired


@router.websocket("/ws/voice")
async def voice(ws: WebSocket):
    """Needs an access token: `Authorization: Bearer <token>` or `?access_token=<token>`."""
    user = await websocket_user(ws)
    await ws.accept()
    if user is None:
        return await ws.close(code=UNAUTHORIZED, reason="Sign in first.")
    session = Session(ws, user)
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
        await session.close()
