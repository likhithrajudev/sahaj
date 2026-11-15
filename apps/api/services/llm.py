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
    max_tokens: Optional[int] = None   # a ceiling on the reply: output is the dear part, and a runaway answer is never wanted

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
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
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


class ChatOpenAI(ChatSarvam):
    """OpenAI's chat completions API. Same wire format as Sarvam's, different address, key header, token-limit name and
    caching hint.

    OpenAI caches the start of a prompt automatically once it is 1,024 tokens or longer, at a discount on those input
    tokens. `prompt_cache_key` steers calls with the same start to the same cache: it is set per kind of prompt (all
    classifier calls share one system prompt, whoever is asking), which is what makes the cache hit across users."""
    model: str = config.OPENAI_CHAT_MODEL
    base_url: str = config.OPENAI_BASE_URL
    cache_key: Optional[str] = None

    @property
    def _llm_type(self) -> str:
        return "openai"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key or config.OPENAI_API_KEY}"}

    def _request(self, messages: List[BaseMessage], stop: Optional[List[str]]) -> dict:
        body = super()._request(messages, stop)
        if "max_tokens" in body:
            body["max_completion_tokens"] = body.pop("max_tokens")
        if self.cache_key or self.affinity:
            body["prompt_cache_key"] = self.cache_key or self.affinity
        return body


# A ceiling on each kind of call's reply, in tokens. Replies are short by design (a sentence or three, a yes or no, a
# small JSON object), so these never cut a good answer and they stop a runaway one costing money.
MAX_TOKENS = {"classify": 150, "fact_check": 8, "answer": 450, "memory": 350, "phrase": 120}


def provider_for(channel: str) -> str:
    """openai or sarvam. Voice conversations use the provider set for voice (Sarvam by default); typed ones use the one
    for text (OpenAI by default). OpenAI is only used when its key is set."""
    wanted = config.VOICE_LLM_PROVIDER if channel == "voice" else config.TEXT_LLM_PROVIDER
    return "openai" if wanted == "openai" and config.OPENAI_API_KEY else "sarvam"


def to_langchain(messages: List[dict]) -> List[BaseMessage]:
    kinds = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
    return [kinds[m["role"]](content=m["content"]) for m in messages]


def model(*, cache=None, **overrides) -> ChatSarvam:
    """A chat model for one call, from the provider for this conversation's channel, carrying its affinity key and,
    optionally, a LangChain cache."""
    session = telemetry.current_session.get()
    if provider_for(telemetry.current_channel.get()) == "openai":
        return ChatOpenAI(api_key=config.OPENAI_API_KEY or "", affinity=session, cache=cache if cache is not None else False, **overrides)
    return ChatSarvam(api_key=config.SARVAM_API_KEY or "", affinity=session, cache=cache if cache is not None else False, **overrides)


async def chat(messages: List[dict], *, purpose: str = "llm", cache=None) -> str:
    """Send chat messages ({"role", "content"} dicts) and return the reply text. `cache` is a LangChain cache to
    use for this call; pass one only for text that holds nothing personal."""
    probe = {"hit": False}
    telemetry.cache_probe.set(probe)
    started = time.perf_counter()
    llm = model(cache=cache, max_tokens=MAX_TOKENS.get(purpose))
    if isinstance(llm, ChatOpenAI):
        llm.cache_key = f"sahaj-{purpose}"   # one cache per kind of prompt, shared by everyone
    provider = llm._llm_type
    reply = await llm.ainvoke(to_langchain(messages), config={"run_name": f"llm:{purpose}", "tags": [f"purpose:{purpose}", f"provider:{provider}"]})
    telemetry.record_llm(purpose, (time.perf_counter() - started) * 1000, reply.usage_metadata, probe["hit"], provider, llm.model)
    return reply.content
