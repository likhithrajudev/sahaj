"""Layer 1 - working memory: the live state of one conversation (masked history, what was just discussed, how many
clarifications in a row, the turn count). Short-lived: it expires WORKING_MEMORY_TTL_SECONDS after the last turn.

It lets a conversation survive a dropped connection (reconnect with ?resume=<session id>) and lets any worker carry on a
conversation another worker started. Kept in Redis when REDIS_URL is set, otherwise in this process. Keys are
sahaj:wm:<tenant>:<user>:<session>, so a session id alone never opens someone else's conversation.

What is NOT kept here: identifiers (the PII vault stays in the process that saw them) and the details of a needs
analysis or loan calculation in progress (personal figures are held only in the live conversation)."""
import json
import logging
import time
from typing import Dict, Optional

import config

log = logging.getLogger("sahaj.working")


def key(tenant: str, user_id: str, session_id: str) -> str:
    return f"sahaj:wm:{tenant}:{user_id}:{session_id}"


class InProcess:
    def __init__(self):
        self.items: Dict[str, tuple] = {}

    async def get(self, k: str) -> Optional[str]:
        item = self.items.get(k)
        if item is None or item[0] < time.monotonic():
            self.items.pop(k, None)
            return None
        return item[1]

    async def set(self, k: str, value: str, ttl: int) -> None:
        if len(self.items) > 10000:   # keep memory bounded: drop what has expired
            now = time.monotonic()
            self.items = {x: v for x, v in self.items.items() if v[0] > now}
        self.items[k] = (time.monotonic() + ttl, value)

    async def delete(self, k: str) -> None:
        self.items.pop(k, None)


class RedisStore:
    def __init__(self, client):
        self.client = client

    async def get(self, k: str) -> Optional[str]:
        return await self.client.get(k)

    async def set(self, k: str, value: str, ttl: int) -> None:
        await self.client.set(k, value, ex=ttl)

    async def delete(self, k: str) -> None:
        await self.client.delete(k)


_backend = None


def backend():
    global _backend
    if _backend is None:
        if config.REDIS_URL:
            import redis.asyncio as redis
            _backend = RedisStore(redis.from_url(config.REDIS_URL, decode_responses=True))
        else:
            _backend = InProcess()
    return _backend


def use(store) -> None:
    global _backend
    _backend = store


async def save(user, session_id: str, state: dict) -> None:
    """Never raises: losing working memory only means a dropped connection cannot be resumed."""
    try:
        await backend().set(key(user.tenant_id, user.id, session_id), json.dumps({"v": 1, "saved_at": time.time(), **state}),
                            config.WORKING_MEMORY_TTL_SECONDS)
    except Exception as e:
        log.warning("Could not save working memory: %s", e)


async def load(user, session_id: str) -> Optional[dict]:
    try:
        raw = await backend().get(key(user.tenant_id, user.id, session_id))
    except Exception as e:
        log.warning("Could not read working memory: %s", e)
        return None
    return json.loads(raw) if raw else None


async def drop(user, session_id: str) -> None:
    try:
        await backend().delete(key(user.tenant_id, user.id, session_id))
    except Exception as e:
        log.warning("Could not drop working memory: %s", e)
