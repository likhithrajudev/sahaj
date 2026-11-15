"""Token-bucket rate limiting, in memory. Each (limit class, client) has a bucket that holds up to `per_minute` requests
and refills steadily. One process only: behind several workers each has its own buckets (use a shared store such as
Redis, or limit at the load balancer, if you need a global figure)."""
import time
from typing import Dict, Optional, Tuple

import config

PURGE_EVERY = 1000   # checks between sweeps of idle buckets
IDLE_SECONDS = 300


class Limiter:
    def __init__(self):
        self._buckets: Dict[Tuple[str, str], list] = {}   # key -> [tokens, last refill time]
        self._checks = 0

    def reset(self) -> None:
        self._buckets.clear()

    def check(self, cls: str, client: str, per_minute: int) -> Optional[float]:
        """None if the request may go ahead, otherwise the seconds to wait."""
        now = time.monotonic()
        self._checks += 1
        if self._checks % PURGE_EVERY == 0:
            self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < IDLE_SECONDS}
        rate = per_minute / 60
        bucket = self._buckets.setdefault((cls, client), [float(per_minute), now])
        bucket[0] = min(float(per_minute), bucket[0] + (now - bucket[1]) * rate)
        bucket[1] = now
        if bucket[0] >= 1:
            bucket[0] -= 1
            return None
        return (1 - bucket[0]) / rate


LIMITER = Limiter()

EXEMPT = ("/health", "/ready", "/metrics")


def classify(path: str) -> Tuple[str, int]:
    """(limit class, requests per minute) for a path. Settings are read per call so they can change at runtime."""
    if path.startswith("/auth/"):
        return "auth", config.RATE_LIMIT_AUTH_PER_MIN
    if path.startswith("/chat/") or path.startswith("/stt"):
        return "chat", config.RATE_LIMIT_CHAT_PER_MIN
    return "default", config.RATE_LIMIT_DEFAULT_PER_MIN
