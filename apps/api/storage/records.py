"""Voice recordings and conversation transcripts, kept in the person's own folder, only with the
`conversation_records` consent. They are registered like any other file, so the person can list, download and delete
them through /files.

  <username>/voice/<session>/<turn>.<ext>          the audio as the person sent it
  <username>/transcripts/<session>/<turn>.json     what was said and answered, personal identifiers masked

A recording is the person's real voice and is stored exactly as received: that is why it needs its own consent."""
import json
import logging
import time
from typing import Optional

from auth.store import User
from storage import blob, files
from trust import consent

log = logging.getLogger("sahaj.records")


def enabled(user: User) -> bool:
    return consent.is_active(user.subject, "conversation_records")


async def _save(user: User, category: str, ext: str, content_type: str, data: bytes, session_id: str, turn: int, label: str) -> None:
    name = files.blob_name(user.username, category, ext, group=session_id, stem=f"{turn:04d}")
    await blob.get().put(name, data, content_type)
    try:
        await files.add(user.id, f"{label}-{session_id[:8]}-{turn:04d}.{ext}", content_type, data, name, category)
    except Exception:
        await blob.get().delete(name)   # no record, so no orphan
        raise


async def save_turn(user: User, session_id: str, turn: int, *, audio: Optional[bytes], user_text: str, reply: str,
                    language: str, channel: str, intent: Optional[str], trace_id: str) -> None:
    """Keep this turn's recording (voice turns) and transcript. Never raises: losing a record must not break a conversation."""
    if not enabled(user):
        return
    try:
        if audio:
            kind = files.sniff(audio)
            content_type, ext = (kind[0], kind[2]) if kind and kind[1] == "audio" else ("application/octet-stream", "bin")
            await _save(user, "voice", ext, content_type, audio, session_id, turn, "recording")
        transcript = {"session": session_id, "turn": turn, "at": time.time(), "channel": channel, "language": language,
                      "intent": intent, "trace_id": trace_id, "user": user_text, "assistant": reply}
        await _save(user, "transcript", "json", "application/json", json.dumps(transcript, ensure_ascii=False, indent=2).encode(),
                    session_id, turn, "transcript")
    except Exception as e:
        log.warning("Could not save a conversation record: %s", e)
