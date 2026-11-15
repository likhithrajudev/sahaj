from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orchestrator.session import Session

router = APIRouter(tags=["Voice"])


@router.websocket("/ws/voice")
async def voice(ws: WebSocket):
    await ws.accept()
    session = Session(ws)
    await session.start()
    try:
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
