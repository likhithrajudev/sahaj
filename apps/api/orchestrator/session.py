import json
import logging
import time
import uuid
from typing import Optional

import httpx
import psycopg
from fastapi import WebSocket

import config
from advisory.flow import AdviceFlow
from auth.store import Unavailable, User
from loan.flow import LoanCalc
from memory import service as memory, store as memory_store
from orchestrator import structure, suggest
from orchestrator.graph import GRAPH
from orchestrator.turn import Turn
from observability import metrics, tracing
from services import telemetry
from storage import records
from usage import ledger as usage_ledger, pricing
from services.stt import transcribe_audio
from services.tts import language_name, resolve_language, speak
from observability.metrics import CONSENT_EVENTS
from desk import escalation, live as desk_live, store as desk
from trust import consent, consents, guardrails, handoff
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

    def __init__(self, ws: WebSocket, user: User, ip: Optional[str] = None):
        self.ws = ws
        self.user = user
        self.ip = ip                        # recorded (hashed) with consent decisions made on this connection
        self._warned = False                # told the person they are close to their spending limit, once
        self._audio: Optional[bytes] = None   # this turn's recording, kept only if the person allows recordings
        self._turns = 0
        self._attested: set = set()         # consents already noted in this conversation's audit trail
        self.channel = "voice"             # how the current turn arrived: voice | text
        self.speaking = True                # speak replies aloud (voice turns); typed turns choose per message
        self.memory: Optional[str] = None   # what Sahaj remembers about this person (only with their memory consent)
        self.id = uuid.uuid4().hex
        self.vault = Vault()
        self.history = []      # PII-masked messages only
        self.agent = None
        self.last_intent: Optional[str] = None
        self.failures = 0
        self.clarifications = 0                  # clarifying questions in a row: too many and a person takes over
        self.case: Optional[dict] = None         # the desk case while a person is (or will be) handling this conversation
        self.handoff_ref = None
        self.flow: Optional[AdviceFlow] = None   # the needs analysis, if one is under way
        self.calc: Optional[LoanCalc] = None     # a loan calculation, if one is under way
        self.pending = None                      # (text, language) waiting for the person's consent to analyse
        self.focus = []                          # plans just recommended or compared: what "the first one" means

    async def start(self, ask_consent: bool = True) -> None:
        await self._load_memory()
        consent.attest(self.id, self.user.subject, self._attested)
        desk_live.join_customer(self.user.id, self)
        try:   # a person may already be handling this customer: carry on with them, not the AI
            self._set_case(await desk.active_for(self.user.id))
        except Exception as e:
            log.warning("Could not check for an open case: %s", e)
        await self.ws.send_json({"type": "session", "id": self.id, "user": self.user.public(),
                                 "memory": self.memory is not None, "case": self._case_view()})
        if ask_consent:
            await self._has_consent()

    async def close(self) -> None:
        """The connection ended: remember what is worth remembering, if the person allows it. The model call this makes
        is counted against the person like any other."""
        desk_live.leave_customer(self.user.id, self)
        if not self.history or not consent.is_active(self.user.subject, "memory"):
            return
        telemetry.current_channel.set(self.channel)
        telemetry.current_session.set(self.id)
        calls: list = []
        telemetry.current_meter.set(calls)
        try:
            await memory.remember(self.user.id, self.history)
        except (httpx.HTTPError, psycopg.Error, RuntimeError, Unavailable) as e:
            log.warning("Could not save memory: %s", e)
        finally:
            await usage_ledger.add(self.user.id, calls)

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
            await self._on_consent(data)
        elif kind == "handoff":
            reason = data.get("reason") if data.get("reason") in ("video_kyc", "callback", "complaint") else "user_requested"
            note = data.get("note") if isinstance(data.get("note"), str) else None
            if reason == "video_kyc" and not consent.is_active(self.user.subject, "video_kyc"):
                return await self.ws.send_json({"type": "consent_required", **consent.required("video_kyc")})
            trace = Trace(self.id)
            await self._handoff(reason, trace, note=self.vault.mask(normalise_digits(note[:500])) if note else None)
            trace.save()
        elif kind == "handoff_cancel":
            await self._cancel_case()
        elif kind == "text":
            text, language = data.get("text"), data.get("language")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                return await self._error(f"A text message must be 1 to {MAX_TEXT} characters.")
            await self.on_text(text, language if isinstance(language, str) else None, data.get("speak") is True)
        else:
            await self._error(f"Unknown message type: {kind}")

    async def _on_consent(self, data: dict) -> None:
        """A consent button. Recorded against the person (so it carries over to their next conversation), with the version
        of the text the client says it showed; the same service as the REST API does the recording and the erasing."""
        purpose, granted = data.get("purpose"), data.get("granted") is True
        version = data.get("version") if isinstance(data.get("version"), str) else None
        channel = getattr(self.ws, "consent_channel", "ws")
        try:
            result = await consents.set_consent(self.user, purpose, granted, channel=channel, version=version, ip=self.ip)
        except consents.ConsentError as e:
            if e.code == "erasure_failed":   # the withdrawal itself was recorded
                self._sync()
                await self.ws.send_json({"type": "consent", "purpose": purpose, "status": "revoked"})
            await self._error(e.message)
            if e.code == "stale_version":    # show them the text as it reads now
                await self.ws.send_json({"type": "consent_required", **consent.required(purpose)})
            return
        CONSENT_EVENTS.labels(purpose, "granted" if granted else "withdrawn").inc()
        self._sync()   # whatever a withdrawal allowed us to hold in this conversation goes now
        if granted and purpose == "memory":
            await self._load_memory()
        consent.attest(self.id, self.user.subject, self._attested)
        for p in result["withdrawn"]:
            await self.ws.send_json({"type": "consent", "purpose": p, "status": "revoked"})
        if granted:
            await self.ws.send_json({"type": "consent", "purpose": purpose, "status": "granted"})
        if granted and purpose == "needs_analysis" and self.pending:
            text, lang = self.pending
            self.pending = None
            await self._guarded(lambda trace: self._respond(text, lang, trace))

    # ---------- inbound: one typed message ----------
    async def on_text(self, text: str, language: Optional[str] = None, speak_reply: bool = False) -> None:
        """A typed message takes the same path as a spoken one, minus speech-to-text. The reply is spoken only on request.
        While a person is handling the conversation, it goes to them instead of the AI."""
        if self.case:
            return await self._relay(text)
        if not await self._has_consent() or not await self._within_budget():
            return
        self.speaking, self.channel = speak_reply, "text"
        self._audio = None
        lang = resolve_language(language or self.user.language)
        await self._guarded(lambda trace: self._typed(text, lang, trace))

    async def _typed(self, text: str, lang: str, trace: Trace) -> None:
        masked = self.vault.mask(normalise_digits(text.strip()))
        trace.add("text", language=lang, text=masked)
        await self.ws.send_json({"type": "user", "text": masked})
        if not await self._escalated(masked, lang, trace):
            await self._respond(masked, lang, trace)

    # ---------- inbound: one recorded utterance ----------
    async def on_audio(self, audio: bytes) -> None:
        if self.case:   # a person is handling it: transcribe and pass the words on
            stt = await transcribe_audio(audio, "voice.webm", "audio/webm")
            return await self._relay(stt.get("transcript", ""))
        if not await self._has_consent() or not await self._within_budget():
            return
        self.speaking, self.channel = True, "voice"
        self._audio = audio
        await self._guarded(lambda trace: self._turn(audio, trace))

    async def _guarded(self, work) -> None:
        trace = Trace(self.id)
        telemetry.current_trace.set(trace)       # the LLM layer records its calls into this turn's trace
        telemetry.current_session.set(self.id)   # and sends this conversation's cache-affinity key
        telemetry.current_channel.set(self.channel)   # voice -> Sarvam, typed -> OpenAI
        calls: list = []
        telemetry.current_meter.set(calls)       # every billable call of this turn lands here
        started, outcome = time.perf_counter(), "ok"
        try:
            await work(trace)
        except (httpx.HTTPError, psycopg.Error, RuntimeError) as e:
            outcome = "error"
            trace.add("error", message=str(e))
            await self._error(str(e))
        finally:
            metrics.TURNS.labels(self.channel, outcome).inc()
            metrics.TURN_SECONDS.labels(self.channel).observe(time.perf_counter() - started)
            await usage_ledger.add(self.user.id, [{**c, "trace_id": trace.id} for c in calls])   # what this turn cost, even a failed one
            trace.save()

    async def _status(self, stage: str) -> None:
        """Progress for the UI: transcribing -> thinking -> checking -> speaking. Carries no content."""
        await self.ws.send_json({"type": "status", "stage": stage})

    async def _turn(self, audio: bytes, trace: Trace) -> None:
        await self._status("transcribing")
        stt = await transcribe_audio(audio, "voice.webm", "audio/webm")
        seconds = pricing.stt_seconds(len(audio))
        telemetry.record_speech("stt", seconds, pricing.stt_cost(seconds))
        lang = resolve_language(stt["language_code"])
        text = self.vault.mask(normalise_digits(stt["transcript"].strip()))
        trace.add("stt", language=lang, transcript=text)
        if not text:
            return await self._error("I didn't catch that.")
        await self.ws.send_json({"type": "user", "text": text})
        if not await self._escalated(text, lang, trace):
            await self._respond(text, lang, trace)

    # ---------- deciding what to say: the graph ----------
    async def _respond(self, text: str, lang: str, trace: Trace) -> None:
        await self._status("thinking")
        result = None
        async for mode, chunk in GRAPH.astream(
            {"text": text, "lang": lang, "language": language_name(lang), "path": []},
            config={"configurable": {"session": self, "trace": trace},
                    **tracing.run_config(session_id=self.id, user_id=self.user.id, language=lang, channel=self.channel,
                                         trace_id=trace.id, memory=self.memory is not None)},
            stream_mode=["updates", "values"],
        ):
            if mode == "values":
                result = chunk  # the last one is the finished state
            elif DECIDING.isdisjoint(chunk):  # a node that wrote a reply has finished: the checks run next
                await self._status("checking")
        trace.add("route", path=result["path"])
        if "intent" in result:
            self.last_intent = result["intent"].intent
        if result.get("handoff"):
            return await self._handoff(result["handoff"], trace, note=text)
        self.clarifications = self.clarifications + 1 if "clarify" in result["path"] else 0
        await self._deliver(result["turn"], result.get("problem"), text, lang, trace)
        if self.clarifications >= config.LOW_CONFIDENCE_HANDOFF_AFTER and not self.case:
            await self._handoff("low_confidence", trace, note=text)

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
            "structured": structure.build(spoken, turn.append, turn.sources, turn.kind),
            "verification": suggest.verification(blocked=bool(problem), from_cache=turn.from_cache, prechecked=turn.prechecked,
                                                 judged=turn.judge and bool(turn.sources) and not turn.prechecked,
                                                 sources=len(turn.sources), kind=turn.kind),
            "suggestions": suggest.for_intent(self.last_intent, lang, turn.kind,
                                              bool(turn.handoff_after or self.failures >= MAX_FAILURES)),
        })
        if self.speaking:
            await self._status("speaking")
            spoken_text, sent = guardrails.strip_citations(shown), False
            try:
                async for chunk in speak(spoken_text, lang):
                    sent = True
                    await self.ws.send_bytes(chunk)
            except Exception as e:   # the speech service being down must not lose the reply, its record or `done`
                log.warning("Text-to-speech failed: %s", e)
                trace.add("tts_error", message=str(e))
                await self.ws.send_json({"type": "status", "stage": "speech_unavailable"})
            if sent:
                telemetry.record_speech("tts", len(spoken_text), pricing.tts_cost(len(spoken_text)))

        self._turns += 1   # kept before `done`, so a client that lists its files on `done` sees this turn's records
        await records.save_turn(self.user, self.id, self._turns, audio=self._audio if self.channel == "voice" else None,
                                user_text=remembered_user, reply=remembered_reply, language=lang, channel=self.channel,
                                intent=self.last_intent, trace_id=trace.id)
        self._audio = None
        await self.ws.send_json({"type": "done"})

        if turn.handoff_after:
            await self._handoff("stuck_in_questions", trace)
        elif self.failures >= MAX_FAILURES:
            await self._handoff("guardrail_failures", trace)

    # ---------- helpers ----------
    def _can_advise(self) -> bool:
        return consent.is_active(self.user.subject, "needs_analysis")

    def _sync(self) -> None:
        """Consents can be withdrawn from elsewhere (the REST API, another device). Whatever they allowed this
        conversation to hold goes at once, whichever route the withdrawal took."""
        subject = self.user.subject
        if not consent.is_active(subject, "memory"):
            self.memory = None
        if not consent.is_active(subject, "needs_analysis"):
            self.flow = self.pending = None
        if not consent.is_active(subject, "conversation"):
            self.calc = self.flow = self.pending = None
            self.history.clear()
            self.vault.clear()

    async def _within_budget(self) -> bool:
        """Stop before spending more than the person's limit for the period. A warning goes out once as they near it."""
        if not config.BUDGET_ENABLED:
            return True
        state = await usage_ledger.status(self.user.id)
        if state["exceeded"]:
            metrics.BUDGET_EVENTS.labels("blocked").inc()
            _, resets = usage_ledger.period()
            await self.ws.send_json({"type": "budget_exceeded", "spent_usd": round(state["spent"], 4), "budget_usd": state["budget"],
                                    "resets_at": resets.isoformat()})
            await self._error("You have used this month's allowance. It renews on " + resets.strftime("%d %B") + ".")
            return False
        if state["warn"] and not self._warned:
            self._warned = True
            metrics.BUDGET_EVENTS.labels("warned").inc()
            await self.ws.send_json({"type": "usage_warning", "spent_usd": round(state["spent"], 4), "budget_usd": state["budget"],
                                     "percent_used": round(100 * state["spent"] / state["budget"], 1)})
        return True

    async def _has_consent(self) -> bool:
        self._sync()
        if consent.is_active(self.user.subject, "conversation"):
            consent.attest(self.id, self.user.subject, self._attested)
            return True
        await self.ws.send_json({"type": "consent_required", **consent.required("conversation")})
        return False

    async def _handoff(self, reason: str, trace: Trace, note: Optional[str] = None) -> None:
        """Bring in a person: open (or join) a case on the executive desk. From now on this conversation's messages go to
        the executive, not the AI, until the case is closed."""
        try:
            case = await handoff.create(self.id, reason, self.history, trace.id, user=self.user,
                                        language=self.user.language, channel=self.channel, note=note)
        except Exception as e:
            log.error("Could not open a case: %s", e)
            trace.add("handoff", reason=reason, reference=None, error=str(e))
            return await self._error("I couldn't reach our team just now. Please try again in a moment.")
        announced = bool(self.case and self.case["id"] == case["id"])   # already told, by the case_attached event
        self._set_case(case)
        trace.add("handoff", reason=reason, reference=case["reference"])
        if not announced:
            await self.ws.send_json({"type": "handoff", "reference": case["reference"], "reason": reason, "case": self._case_view()})

    def _set_case(self, case: Optional[dict]) -> None:
        self.case = case
        self.handoff_ref = case["reference"] if case else None

    def _case_view(self) -> Optional[dict]:
        if not self.case:
            return None
        return {"id": self.case["id"], "reference": self.case["reference"], "kind": self.case["kind"],
                "status": "with_executive" if self.case["status"] == "assigned" else "waiting",
                "priority": self.case["priority"]}

    async def _relay(self, text: str) -> None:
        """A message while a person handles the conversation: masked, kept on the case, passed to the executive live."""
        masked = self.vault.mask(normalise_digits((text or "").strip()))[:2000]
        if not masked:
            return
        await self.ws.send_json({"type": "user", "text": masked})
        try:
            message = await desk.add_message(self.case["id"], "customer", masked)
        except Exception as e:
            log.error("Could not store a message on case %s: %s", self.case["id"], e)
            return await self._error("Your message could not be delivered. Please try again.")
        await desk_live.to_executives({"type": "customer_message", "case_id": self.case["id"], "text": masked,
                                       "at": message["at"].isoformat()})
        if self.case["status"] == "open":
            await self._status("waiting_for_executive")

    async def _cancel_case(self) -> None:
        if not self.case:
            return await self._error("No one is handling this conversation, so there is nothing to cancel.")
        case = await desk.close(self.case["id"], "cancelled", f"user:{self.user.id}", "cancelled_by_customer", None)
        if case:
            await desk_live.to_executives({"type": "case_closed", "case_id": case["id"], "status": "cancelled"})
        self._set_case(None)
        await self.ws.send_json({"type": "handoff_closed", "status": "cancelled"})

    async def on_desk_event(self, event: dict) -> None:
        """Something happened on this person's case at the desk: it was opened (perhaps from another device), an executive
        joined, wrote, scheduled, or closed it."""
        if event["type"] == "case_attached":
            if not (self.case and self.case["id"] == event["case_id"]):
                self._set_case(dict(event["case"]))
                await self.ws.send_json({"type": "handoff", "reference": self.case["reference"], "reason": self.case["reason"],
                                         "case": self._case_view()})
            return
        if not self.case or event.get("case_id") != self.case["id"]:
            return
        if event["type"] == "agent_joined":
            self.case["status"] = "assigned"
        elif event["type"] == "agent_left":
            self.case["status"] = "open"
        await self.ws.send_json(event)
        if event["type"] == "handoff_closed":
            self._set_case(None)   # back to the AI

    async def _escalated(self, text: str, lang: str, trace: Trace) -> bool:
        """A complaint or someone in distress goes to a person at once, whatever the AI could have said."""
        reason = escalation.detect(text)
        if not reason:
            return False
        trace.add("escalation", reason=reason)
        await self._deliver(Turn(text=escalation.acknowledgement(reason, lang), kind="answer", agent="general", judge=False),
                            None, text, lang, trace)
        await self._handoff(reason, trace, note=text)
        return True

    async def _error(self, message: str) -> None:
        await self.ws.send_json({"type": "error", "message": message})
