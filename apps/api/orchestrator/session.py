import json
import logging
import uuid
from typing import Optional

import httpx
import psycopg
from fastapi import WebSocket

from advisory.flow import AdviceFlow
from auth.store import Unavailable, User
from loan.flow import LoanCalc
from memory import service as memory, store as memory_store
from orchestrator.graph import GRAPH
from orchestrator.turn import Turn
from services import telemetry
from services.stt import transcribe_audio
from services.tts import language_name, resolve_language, speak
from trust import consent, guardrails, handoff
from trust.audit import Trace
from trust.pii import Vault, normalise_digits

log = logging.getLogger("sahaj.session")

MAX_MESSAGES = 20  # recent user/assistant messages kept as context
MAX_FAILURES = 2   # blocked replies in a row before a human is brought in
MAX_TEXT = 2000    # characters in one typed message
# Graph nodes that only decide what to do. Once a node that produces a reply finishes, the checks begin.
DECIDING = {"continue_active", "classify", "guard", "handoff"}


class Session:
    """One conversation. The LangGraph orchestrator (orchestrator/graph.py) decides what to say; this class handles
    the connection: consent, speech in and out, history, and handing over to a person."""

    def __init__(self, ws: WebSocket, user: User):
        self.ws = ws
        self.user = user
        self.speaking = True                # speak replies aloud (voice turns); typed turns choose per message
        self.memory: Optional[str] = None   # what Sahaj remembers about this person (only with their memory consent)
        self.id = uuid.uuid4().hex
        self.vault = Vault()
        self.history = []      # PII-masked messages only
        self.agent = None
        self.last_intent: Optional[str] = None
        self.failures = 0
        self.handoff_ref = None
        self.flow: Optional[AdviceFlow] = None   # the needs analysis, if one is under way
        self.calc: Optional[LoanCalc] = None     # a loan calculation, if one is under way
        self.pending = None                      # (text, language) waiting for the person's consent to analyse
        self.focus = []                          # plans just recommended or compared: what "the first one" means

    async def start(self, ask_consent: bool = True) -> None:
        await self._load_memory()
        await self.ws.send_json({"type": "session", "id": self.id, "user": self.user.public(),
                                 "memory": self.memory is not None})
        if ask_consent:
            await self._has_consent()

    async def close(self) -> None:
        """The connection ended: remember what is worth remembering, if the person allows it."""
        if not self.history or not consent.is_active(self.user.subject, "memory"):
            return
        try:
            await memory.remember(self.user.id, self.history)
        except (httpx.HTTPError, psycopg.Error, RuntimeError, Unavailable) as e:
            log.warning("Could not save memory: %s", e)

    async def _load_memory(self) -> None:
        self.memory = None
        if not consent.is_active(self.user.subject, "memory"):
            return
        try:
            self.memory = memory.render(await memory_store.for_prompt(self.user.id))
        except (psycopg.Error, RuntimeError, Unavailable) as e:
            log.warning("Could not load memory: %s", e)

    # ---------- inbound: JSON control messages ----------
    async def on_control(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            kind = data["type"]
        except (ValueError, KeyError, TypeError):
            return await self._error("Expected a JSON message with a 'type'.")

        if kind == "consent":
            purpose = data.get("purpose")
            if purpose not in consent.PURPOSES:
                return await self._error(f"Unknown consent purpose: {purpose}")
            granted = data.get("granted") is True
            subject = self._subject(purpose)  # memory belongs to the person, the rest to this conversation
            if granted:
                consent.grant(subject, purpose, channel="ws")
                if purpose == "memory":
                    await self._load_memory()
            else:
                consent.revoke(subject, purpose, channel="ws")
                if purpose == "memory":  # withdrawn: forget what is held, here and in storage
                    self.memory = None
                    try:
                        await memory_store.delete_all(self.user.id)
                    except (psycopg.Error, RuntimeError, Unavailable) as e:
                        log.error("Could not erase memory: %s", e)
                        return await self._error("I couldn't erase your memory just now. Please try again.")
                self.pending = None
                if purpose in ("conversation", "needs_analysis"):  # withdrawn: forget the details we hold
                    self.flow = None
                if purpose == "conversation":
                    self.calc = None
                    self.history.clear()
                    self.vault.clear()
            status = "granted" if consent.is_active(subject, purpose) else "revoked"
            await self.ws.send_json({"type": "consent", "purpose": purpose, "status": status})
            if granted and purpose == "needs_analysis" and self.pending:
                text, lang = self.pending
                self.pending = None
                await self._guarded(lambda trace: self._respond(text, lang, trace))
        elif kind == "handoff":
            trace = Trace(self.id)
            await self._handoff("user_requested", trace)
            trace.save()
        elif kind == "text":
            text, language = data.get("text"), data.get("language")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                return await self._error(f"A text message must be 1 to {MAX_TEXT} characters.")
            await self.on_text(text, language if isinstance(language, str) else None, data.get("speak") is True)
        else:
            await self._error(f"Unknown message type: {kind}")

    # ---------- inbound: one typed message ----------
    async def on_text(self, text: str, language: Optional[str] = None, speak_reply: bool = False) -> None:
        """A typed message takes the same path as a spoken one, minus speech-to-text. The reply is spoken only on request."""
        if self.handoff_ref:
            return await self.ws.send_json({"type": "handoff", "reference": self.handoff_ref})
        if not await self._has_consent():
            return
        self.speaking = speak_reply
        lang = resolve_language(language or self.user.language)
        await self._guarded(lambda trace: self._typed(text, lang, trace))

    async def _typed(self, text: str, lang: str, trace: Trace) -> None:
        masked = self.vault.mask(normalise_digits(text.strip()))
        trace.add("text", language=lang, text=masked)
        await self.ws.send_json({"type": "user", "text": masked})
        await self._respond(masked, lang, trace)

    # ---------- inbound: one recorded utterance ----------
    async def on_audio(self, audio: bytes) -> None:
        if self.handoff_ref:
            return await self.ws.send_json({"type": "handoff", "reference": self.handoff_ref})
        if not await self._has_consent():
            return
        self.speaking = True
        await self._guarded(lambda trace: self._turn(audio, trace))

    async def _guarded(self, work) -> None:
        trace = Trace(self.id)
        telemetry.current_trace.set(trace)       # the LLM layer records its calls into this turn's trace
        telemetry.current_session.set(self.id)   # and sends this conversation's cache-affinity key
        try:
            await work(trace)
        except (httpx.HTTPError, psycopg.Error, RuntimeError) as e:
            trace.add("error", message=str(e))
            await self._error(str(e))
        finally:
            trace.save()

    async def _status(self, stage: str) -> None:
        """Progress for the UI: transcribing -> thinking -> checking -> speaking. Carries no content."""
        await self.ws.send_json({"type": "status", "stage": stage})

    async def _turn(self, audio: bytes, trace: Trace) -> None:
        await self._status("transcribing")
        stt = await transcribe_audio(audio, "voice.webm", "audio/webm")
        lang = resolve_language(stt["language_code"])
        text = self.vault.mask(normalise_digits(stt["transcript"].strip()))
        trace.add("stt", language=lang, transcript=text)
        if not text:
            return await self._error("I didn't catch that.")
        await self.ws.send_json({"type": "user", "text": text})
        await self._respond(text, lang, trace)

    # ---------- deciding what to say: the graph ----------
    async def _respond(self, text: str, lang: str, trace: Trace) -> None:
        await self._status("thinking")
        result = None
        async for mode, chunk in GRAPH.astream(
            {"text": text, "lang": lang, "language": language_name(lang), "path": []},
            config={"configurable": {"session": self, "trace": trace}}, stream_mode=["updates", "values"],
        ):
            if mode == "values":
                result = chunk  # the last one is the finished state
            elif DECIDING.isdisjoint(chunk):  # a node that wrote a reply has finished: the checks run next
                await self._status("checking")
        trace.add("route", path=result["path"])
        if "intent" in result:
            self.last_intent = result["intent"].intent
        if result.get("handoff"):
            return await self._handoff(result["handoff"], trace)
        await self._deliver(result["turn"], result.get("problem"), text, lang, trace)

    # ---------- delivering ----------
    async def _deliver(self, turn: Turn, problem: Optional[str], text: str, lang: str, trace: Trace) -> None:
        """Send, speak and remember a reply that the graph has already checked."""
        if turn.request_consent:
            await self.ws.send_json({"type": "consent_required", **consent.required(turn.request_consent)})

        if problem:
            self.failures += 1
            spoken = turn.fallback or guardrails.fallback(lang)  # the blocked text is never shown, spoken or remembered
            if turn.on_blocked:
                turn.on_blocked()
        else:
            self.failures = 0
            spoken = turn.text
        shown = " ".join([spoken] + turn.append)  # fixed text (such as disclosures) goes with the answer either way

        cited = guardrails.citations(shown)
        # The history feeds hand-off packets, so personal answers are replaced by a placeholder.
        remembered_user = "[gave personal details]" if turn.sensitive_input else text
        remembered_reply = "[read back the person's details]" if turn.kind == "confirm" else guardrails.strip_citations(shown)
        self.history = (self.history + [
            {"role": "user", "content": remembered_user, "intent": self.last_intent},
            {"role": "assistant", "content": remembered_reply},  # tags would prime cross-agent citations
        ])[-MAX_MESSAGES:]

        if turn.card:  # structured data is deterministic, so it is shown even if the narration was blocked
            if "plans" in turn.card:  # what "the first one" means in the next question
                self.focus = [p.get("product_id") or p["id"] for p in turn.card["plans"]]
            await self.ws.send_json({"type": "card", "kind": turn.kind, "card": turn.card, "trace_id": trace.id})
        await self.ws.send_json({
            "type": "assistant", "agent": turn.agent, "text": shown, "trace_id": trace.id,
            "citations": [{"id": c, "text": turn.sources[c]} for c in cited if c in turn.sources],
        })
        if self.speaking:
            await self._status("speaking")
            async for chunk in speak(guardrails.strip_citations(shown), lang):
                await self.ws.send_bytes(chunk)
        await self.ws.send_json({"type": "done"})

        if turn.handoff_after:
            await self._handoff("stuck_in_questions", trace)
        elif self.failures >= MAX_FAILURES:
            await self._handoff("guardrail_failures", trace)

    # ---------- helpers ----------
    def _subject(self, purpose: str) -> str:
        """Memory consent belongs to the person; every other consent to this conversation."""
        return self.user.subject if purpose == "memory" else self.id

    def _can_advise(self) -> bool:
        return consent.is_active(self.id, "needs_analysis")

    async def _has_consent(self) -> bool:
        if consent.is_active(self.id, "conversation"):
            return True
        await self.ws.send_json({"type": "consent_required", **consent.required("conversation")})
        return False

    async def _handoff(self, reason: str, trace: Trace) -> None:
        self.handoff_ref = await handoff.create(self.id, reason, self.history, trace.id)
        trace.add("handoff", reason=reason, reference=self.handoff_ref)
        await self.ws.send_json({"type": "handoff", "reference": self.handoff_ref, "reason": reason})

    async def _error(self, message: str) -> None:
        await self.ws.send_json({"type": "error", "message": message})
