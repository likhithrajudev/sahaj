"""The one path to Sarvam's chat model, as a LangChain chat model so LangGraph, prompts, structured output and
LangChain caching all share it. Adds retries, the session-affinity header (which is what makes Sarvam's prefix
cache hit) and per-call telemetry."""
import asyncio
import time
from typing import Any, List, Optional

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import config
from services import telemetry

RETRY_STATUS = {429, 500, 502, 503, 504}
ROLES = {"system": "system", "human": "user", "ai": "assistant"}


class ChatSarvam(BaseChatModel):
    model: str = config.SARVAM_CHAT_MODEL
    base_url: str = config.SARVAM_BASE_URL
    api_key: str = ""
    affinity: Optional[str] = None   # same value on every call of a conversation => Sarvam can reuse its prompt cache
    max_attempts: int = 4
    timeout: float = 60.0

    @property
    def _llm_type(self) -> str:
        return "sarvam"

    @property
    def _identifying_params(self) -> dict:  # part of LangChain's cache key, so never the key or the affinity value
        return {"model": self.model, "base_url": self.base_url}

    # ---- wire format
    def _request(self, messages: List[BaseMessage], stop: Optional[List[str]]) -> dict:
        body = {"model": self.model, "messages": [{"role": ROLES.get(m.type, "user"), "content": m.content} for m in messages]}
        if stop:
            body["stop"] = stop
        return body

    def _headers(self) -> dict:
        headers = {"api-subscription-key": self.api_key or config.SARVAM_API_KEY}
        if self.affinity and config.SARVAM_AFFINITY:
            headers["x-session-affinity"] = self.affinity
        return headers

    @staticmethod
    def _result(data: dict) -> ChatResult:
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        message = AIMessage(
            content=data["choices"][0]["message"]["content"],
            usage_metadata={
                "input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "input_token_details": {"cache_read": details.get("cached_tokens") or 0,
                                        "cache_creation": details.get("created_cache_tokens") or 0},
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    # ---- calls (async is what the app uses; sync keeps the LangChain interface complete)
    async def _agenerate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                         run_manager: Optional[AsyncCallbackManagerForLLMRun] = None, **kwargs: Any) -> ChatResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_attempts):
                r = await client.post(f"{self.base_url}/v1/chat/completions", headers=self._headers(),
                                      json=self._request(messages, stop))
                if r.status_code not in RETRY_STATUS or attempt == self.max_attempts - 1:
                    break
                retry_after = r.headers.get("retry-after", "")
                await asyncio.sleep(float(retry_after) if retry_after.isdigit() else 2 ** attempt)  # 1s, 2s, 4s
        r.raise_for_status()
        return self._result(r.json())

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs: Any) -> ChatResult:
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(self.max_attempts):
                r = client.post(f"{self.base_url}/v1/chat/completions", headers=self._headers(),
                                json=self._request(messages, stop))
                if r.status_code not in RETRY_STATUS or attempt == self.max_attempts - 1:
                    break
                time.sleep(2 ** attempt)
        r.raise_for_status()
        return self._result(r.json())


def to_langchain(messages: List[dict]) -> List[BaseMessage]:
    kinds = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
    return [kinds[m["role"]](content=m["content"]) for m in messages]


def model(*, cache=None, **overrides) -> ChatSarvam:
    """A chat model for one call: carries this conversation's affinity key and, optionally, a LangChain cache."""
    return ChatSarvam(api_key=config.SARVAM_API_KEY, affinity=telemetry.current_session.get(),
                      cache=cache if cache is not None else False, **overrides)


async def chat(messages: List[dict], *, purpose: str = "llm", cache=None) -> str:
    """Send chat messages ({"role", "content"} dicts) and return the reply text. `cache` is a LangChain cache to
    use for this call; pass one only for text that holds nothing personal."""
    probe = {"hit": False}
    telemetry.cache_probe.set(probe)
    started = time.perf_counter()
    reply = await model(cache=cache).ainvoke(to_langchain(messages))
    telemetry.record_llm(purpose, (time.perf_counter() - started) * 1000, reply.usage_metadata, probe["hit"])
    return reply.content
