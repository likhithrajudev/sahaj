"""Intent classification: one structured decision per user message, with a confidence."""
from typing import Literal, Optional

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

import config
from orchestrator.prompts import CLASSIFIER_SYSTEM, CLASSIFIER_USER
from services import cache, llm

IntentName = Literal[
    "insurance_explain", "insurance_advice", "insurance_compare",
    "loan_explain", "loan_calculator", "loan_guidance", "loan_rates_comparison",
    "human_handoff", "greeting", "out_of_scope",
]
INTENTS = IntentName.__args__


class Intent(BaseModel):
    intent: IntentName
    confidence: float = Field(ge=0, le=1)
    detail: Literal["brief", "deep"] = "brief"
    reason: str = ""

    @property
    def deep(self) -> bool:
        return self.detail == "deep"


PARSER = PydanticOutputParser(pydantic_object=Intent)
# System text has no placeholders, so every call starts with the identical prompt (and a cacheable prefix).
PROMPT = ChatPromptTemplate.from_messages([("system", "{system}"), ("human", CLASSIFIER_USER)])


def _looks_personal(text: str) -> bool:
    """Anything that might carry a person's details is never cached: amounts, ages, masked identifiers."""
    return any(ch.isdigit() for ch in text) or "[" in text


async def classify(text: str, previous: Optional[str], in_flow: bool, asking: Optional[str]) -> Intent:
    """What the user wants. If the model's answer cannot be parsed twice, returns out_of_scope with confidence 0,
    which the graph treats as 'ask the user to clarify' rather than guessing."""
    messages = PROMPT.format_messages(system=CLASSIFIER_SYSTEM, previous=previous or "none",
                                      in_flow="yes" if in_flow else "no", asking=asking or "nothing", message=text)
    plain = [{"role": {"system": "system", "human": "user"}[m.type], "content": m.content} for m in messages]
    use_cache = cache.CLASSIFIER_CACHE if config.APP_CACHE_ENABLED and not in_flow and not _looks_personal(text) else None

    for attempt in range(2):
        reply = await llm.chat(plain, purpose="classify", cache=use_cache)
        try:
            return PARSER.parse(reply[reply.find("{"):reply.rfind("}") + 1])
        except (OutputParserException, ValueError):
            # Never keep an unparseable answer in the cache.
            if use_cache is not None:
                use_cache.clear()
            plain = plain + [{"role": "assistant", "content": reply},
                             {"role": "user", "content": "That was not valid. Reply with the JSON object only."}]
            use_cache = None
    return Intent(intent="out_of_scope", confidence=0.0, reason="unparseable classifier output")
