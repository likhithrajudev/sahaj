"""Intent classification: one structured decision per user message, with a confidence."""
import unicodedata
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
    search: str = ""   # the question as an English search phrase: documents are in English, questions often are not

    @property
    def deep(self) -> bool:
        return self.detail == "deep"


PARSER = PydanticOutputParser(pydantic_object=Intent)
# System text has no placeholders, so every call starts with the identical prompt (and a cacheable prefix).
PROMPT = ChatPromptTemplate.from_messages([("system", "{system}"), ("human", CLASSIFIER_USER)])


def _looks_personal(text: str) -> bool:
    """Anything that might carry a person's details is never cached: amounts, ages, masked identifiers."""
    return any(ch.isdigit() for ch in text) or "[" in text


GREETINGS = {"hi", "hii", "hello", "hey", "hey there", "namaste", "namaskar", "namaskaram", "vanakkam", "good morning",
             "good afternoon", "good evening", "नमस्ते", "नमस्कार", "हेलो", "हाय"}
HUMAN = {"talk to a human", "talk to a person", "speak to a human", "speak to a person", "human please", "agent please",
         "connect me to a human", "connect me to a person", "i want a human", "i want to talk to a person"}


def fast_intent(text: str) -> Optional[Intent]:
    """A message that is only a greeting, or only a request for a person, needs no model to be understood: this saves the
    longest prompt in the system on the most common opening message. Anything else goes to the classifier."""
    # Keep letters, combining marks (Hindi vowel signs are marks) and digits; drop punctuation and symbols.
    plain = " ".join("".join(c for c in text.lower() if c.isspace() or unicodedata.category(c)[0] in "LMN").split())
    if plain in GREETINGS:
        return Intent(intent="greeting", confidence=1.0, reason="a plain greeting")
    if plain in HUMAN:
        return Intent(intent="human_handoff", confidence=1.0, reason="asked for a person")
    return None


async def classify(text: str, previous: Optional[str], in_flow: bool, asking: Optional[str]) -> Intent:
    """What the user wants. If the model's answer cannot be parsed twice, returns out_of_scope with confidence 0,
    which the graph treats as 'ask the user to clarify' rather than guessing."""
    if not in_flow and (quick := fast_intent(text)):
        return quick
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
