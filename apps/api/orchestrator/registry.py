"""Conversations that continue across HTTP requests (the SSE chat endpoint). A WebSocket keeps its Session alive for
the length of the connection; over HTTP each request is separate, so Sessions are kept here for a while.

In memory and per process: run one worker, or route a session's requests to the same worker."""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from auth.store import User
from orchestrator.session import Session

log = logging.getLogger("sahaj.registry")

IDLE_SECONDS = 30 * 60
MAX_PER_USER = 5


class QueueSocket:
    """Stands in for the WebSocket: events go to a queue the HTTP response drains. There is no audio over HTTP."""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def send_json(self, data: dict) -> None:
        await self.queue.put(data)

    async def send_bytes(self, data: bytes) -> None:
        pass


@dataclass
class Entry:
    session: Session
    user_id: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one turn at a time per conversation
    last_used: float = field(default_factory=time.monotonic)


_entries: Dict[str, Entry] = {}


async def _end(entry: Entry) -> None:
    async with entry.lock:
        await entry.session.close()  # saves memory, if the person allows it


async def sweep() -> None:
    now = time.monotonic()
    for sid in [k for k, e in _entries.items() if now - e.last_used > IDLE_SECONDS and not e.lock.locked()]:
        await _end(_entries.pop(sid))


def acquire(user: User, session_id: Optional[str]) -> Tuple[Optional[Entry], bool]:
    """(entry, created). An unknown id, or one that belongs to someone else, gives (None, False)."""
    if session_id:
        entry = _entries.get(session_id)
        if entry is None or entry.user_id != user.id:
            return None, False
        entry.last_used = time.monotonic()
        return entry, False
    mine = sorted((e for e in _entries.values() if e.user_id == user.id), key=lambda e: e.last_used)
    if len(mine) >= MAX_PER_USER:  # the least recently used goes
        old = mine[0]
        _entries.pop(old.session.id, None)
        asyncio.create_task(_end(old))
    entry = Entry(Session(QueueSocket(asyncio.Queue()), user), user.id)
    _entries[entry.session.id] = entry
    return entry, True


async def end(user: User, session_id: str) -> bool:
    entry = _entries.get(session_id)
    if entry is None or entry.user_id != user.id:
        return False
    _entries.pop(session_id)
    await _end(entry)
    return True


async def shutdown() -> None:
    for sid in list(_entries):
        await _end(_entries.pop(sid))
