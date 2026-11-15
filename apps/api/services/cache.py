"""In-memory caches. Process memory only: nothing is written to disk, entries expire, and callers decide what is
safe to store (never anything from a personal-details conversation)."""
import time
from collections import OrderedDict
from typing import Any, Optional, Sequence

from langchain_core.caches import BaseCache

import config
from services import telemetry


class TTLStore:
    """A small LRU with expiry and hit counters."""

    def __init__(self, ttl: int = None, max_entries: int = None):
        self.ttl = config.CACHE_TTL_SECONDS if ttl is None else ttl
        self.max_entries = config.CACHE_MAX_ENTRIES if max_entries is None else max_entries
        self._data: "OrderedDict[Any, tuple]" = OrderedDict()
        self.hits = self.misses = 0

    def get(self, key) -> Optional[Any]:
        entry = self._data.get(key)
        if entry is None or entry[0] < time.time():
            self._data.pop(key, None)
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return entry[1]

    def set(self, key, value) -> None:
        self._data[key] = (time.time() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"entries": len(self), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else None}


class LLMCache(BaseCache):
    """LangChain cache interface over a TTLStore. Used only for model calls on non-personal text."""

    def __init__(self, store: TTLStore = None):
        self.store = store or TTLStore()

    def lookup(self, prompt: str, llm_string: str) -> Optional[Sequence]:
        value = self.store.get((prompt, llm_string))
        if value is not None:
            probe = telemetry.cache_probe.get()
            if probe is not None:
                probe["hit"] = True
        return value

    def update(self, prompt: str, llm_string: str, return_val: Sequence) -> None:
        self.store.set((prompt, llm_string), return_val)

    def clear(self, **kwargs: Any) -> None:
        self.store.clear()

    async def alookup(self, prompt: str, llm_string: str) -> Optional[Sequence]:
        return self.lookup(prompt, llm_string)

    async def aupdate(self, prompt: str, llm_string: str, return_val: Sequence) -> None:
        self.update(prompt, llm_string, return_val)

    async def aclear(self, **kwargs: Any) -> None:
        self.clear()


# One instance per kind of thing cached, so each can be inspected and cleared on its own.
CLASSIFIER_CACHE = LLMCache()     # intent of a message (non-personal messages only)
ANSWER_CACHE = TTLStore()         # guardrail-verified answers, keyed by question + language + clause hashes
EMBEDDING_CACHE = TTLStore(ttl=24 * 3600, max_entries=2048)  # query text -> embedding vector


def all_stats() -> dict:
    return {"classifier": CLASSIFIER_CACHE.store.stats(), "verified_answers": ANSWER_CACHE.stats(),
            "embeddings": EMBEDDING_CACHE.stats()}
