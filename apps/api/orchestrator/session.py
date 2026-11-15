import json
import logging
import re
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
from memory import episodic, procedural, semantic, service as memory, store as memory_store, working
from orchestrator import structure, suggest
from orchestrator import commands
from orchestrator.graph import GRAPH
from orchestrator.turn import Turn
from observability import metrics, tracing
from services import telemetry
from storage import records
from usage import ledger as usage_ledger, pricing
from services.stt import transcribe_audio
from services.tts import SUPPORTED_LANGUAGES, language_name, resolve_language, resolve_text_language, speak
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


def _inventory_request(text: str) -> bool:
    action = re.search(r"\b(track|add|save|update|record|remember|manage)\b|रख|जोड़|अपडेट|सेव|दर्ज|रिकॉर्ड", text, re.I)
    asset = re.search(r"\b(credit.?cards?|cards?|em[ií]s?|loans?|inventory|due dates?)\b|क्रेडिट.?कार्ड|कार्ड|ईएमआई|लोन|किस्त", text, re.I)
    return bool(action and asset and not re.search(r"\bloan application\b", text, re.I))


class Session:
    """One conversation. The LangGraph orchestrator (orchestrator/graph.py) decides what to say; this class handles
    the connection: consent, speech in and out, history, and handing over to a person."""

    def __init__(self, ws: WebSocket, user: User, ip: Optional[str] = None, resume: Optional[str] = None):
        from datetime import datetime, timezone
        self.ws = ws
        self.user = user
        self.started_at = datetime.now(timezone.utc)
        self._resume = resume                 # a session id whose working memory to pick up, after a dropped connection
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
        self.inventory_flow = None
        self.pending_inventory = None
        self.pending = None                      # (text, language) waiting for the person's consent to analyse
        self.focus = []                          # plans just recommended or compared: what "the first one" means

    async def start(self, ask_consent: bool = True) -> None:
        resumed = await self.restore(self._resume) if self._resume else False
        await self._load_memory()
        consent.attest(self.id, self.user.subject, self._attested)
        desk_live.join_customer(self.user.id, self)
        try:   # a person may already be handling this customer: carry on with them, not the AI
            self._set_case(await desk.active_for(self.user.id))
        except Exception as e:
            log.warning("Could not check for an open case: %s", e)
        await self.ws.send_json({"type": "session", "id": self.id, "user": self.user.public(),
                                 "memory": self.memory is not None, "case": self._case_view(), "resumed": resumed})
        if ask_consent:
            await self._has_consent()

    def snapshot(self) -> dict:
        """Working memory: what is needed to carry this conversation on elsewhere. Masked history only; no identifiers
        and no needs-analysis or calculator figures."""
        return {"session_id": self.id, "user_id": self.user.id, "history": self.history, "last_intent": self.last_intent,
                "focus": self.focus, "clarifications": self.clarifications, "turns": self._turns, "channel": self.channel,
                "started_at": self.started_at.isoformat()}

    async def restore(self, session_id: str) -> bool:
        """Pick up a conversation from working memory (this person's own only: the key includes tenant and user)."""
        from datetime import datetime
        state = await working.load(self.user, session_id)
        if not state or state.get("user_id") != self.user.id:
            return False
        self.id = session_id
        self.history, self.last_intent, self.focus = state["history"], state["last_intent"], state["focus"]
        self.clarifications, self._turns, self.channel = state["clarifications"], state["turns"], state["channel"]
        self.started_at = datetime.fromisoformat(state["started_at"])
        return True

    async def close(self) -> None:
        """The connection ended: remember what is worth remembering, if the person allows it. The model call this makes
        is counted against the person like any other."""
        desk_live.leave_customer(self.user.id, self)
        import tenancy
        tenancy.use(self.user.tenant_id)   # close() can be called from another request (an idle sweep): act as this person's tenant
        if not self.history or not consent.is_active(self.user.subject, "memory"):
            return
        telemetry.current_channel.set(self.channel)
        telemetry.current_session.set(self.id)
        calls: list = []
        telemetry.current_meter.set(calls)
        try:
            await memory.remember_conversation(self)   # episodic (what happened) + semantic (stable facts)
        except (httpx.HTTPError, psycopg.Error, RuntimeError, Unavailable) as e:
            log.warning("Could not save memory: %s", e)
        finally:
            await usage_ledger.add(self.user.id, calls)

    async def _load_memory(self) -> None:
        self.memory = None
        if not consent.is_active(self.user.subject, "memory"):
            return
        try:   # the recent picture at the start; each turn then recalls what bears on its own question
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
        if granted and purpose == "conversation" and self.pending_inventory:
            await self.ws.send_json({"type": "consent_required", **consent.required("financial_profile")})
        if not granted and purpose == "financial_profile":
            self.pending_inventory = None
        if not granted and purpose == "conversation":
            self.pending_inventory = None
        if granted and purpose == "financial_profile" and self.pending_inventory:
            action, lang = self.pending_inventory
            self.pending_inventory = None
            await self._guarded(lambda trace: self._inventory_action(action, lang, trace))

    # ---------- inbound: one typed message ----------
    async def on_text(self, text: str, language: Optional[str] = None, speak_reply: bool = False) -> None:
        """A typed message takes the same path as a spoken one, minus speech-to-text. The reply is spoken only on request.
        While a person is handling the conversation, it goes to them instead of the AI."""
        if self.case:
            return await self._relay(text)
        self.speaking, self.channel = speak_reply, "text"
        self._audio = None
        lang = resolve_text_language(language, self.user.language, text)
        if commands.parse(text):
            return await self._guarded(lambda trace: self._typed(text, lang, trace))
        if not await self._has_consent() or not await self._within_budget():
            return
        await self._guarded(lambda trace: self._typed(text, lang, trace))

    async def _typed(self, text: str, lang: str, trace: Trace) -> None:
        masked = self.vault.mask(normalise_digits(text.strip()))
        sensitive = bool(self.inventory_flow and self.inventory_flow.active)
        inventory_request = _inventory_request(masked)
        trace.add("text", language=lang, text="[withheld: financial inventory details]" if sensitive or inventory_request else masked)
        await self.ws.send_json({"type": "user", "text": masked})
        command = commands.parse(masked)
        if command:
            return await self._run_command(command, lang, trace)
        self.pending_inventory = None
        if inventory_request:
            if consent.is_active(self.user.subject, "financial_profile"):
                turn = await self._inventory_action("update", lang, trace, initial_request=masked)
            else:
                self.pending_inventory = ("update", lang)
                turn = Turn(text="Before I store card or EMI details, please review the financial inventory permission on your screen.",
                            kind="ask", agent="general", judge=False, prechecked=True, sensitive_input=True,
                            request_consent="financial_profile")
            trace.add("command", name="/inventory")
            return await self._deliver(turn, None, text, lang, trace)
        if sensitive or not await self._escalated(masked, lang, trace):
            await self._respond(masked, lang, trace)

    async def _run_command(self, command: commands.Command, lang: str, trace: Trace) -> None:
        from auth import store
        from usage import ledger as usage_ledger

        names = ", ".join(f"{code} ({name})" for code, name in SUPPORTED_LANGUAGES.items())
        if command.name not in commands.COMMANDS:
            reply = "Unknown shortcut. Use /help to see the available text commands."
        elif command.name == "/help":
            reply = "Text shortcuts: /usage shows this month's usage and budget; /clear starts a fresh conversation; " \
                    "/language lists supported languages; /language <code> changes your preferred language; " \
                    "/inventory adds or updates your cards and EMIs; /inventory show views them; /cancel cancels an update."
        elif command.name == "/language":
            if not command.argument:
                reply = f"Supported languages: {names}"
            else:
                language = resolve_language(command.argument)
                if language != command.argument:
                    reply = f"Unsupported language code. Supported languages: {names}"
                else:
                    self.user = await store.update_profile(self.user.id, {"language": language}) or self.user
                    reply = f"Preferred language changed to {language} ({SUPPORTED_LANGUAGES[language]})."
        elif command.name == "/clear":
            await working.drop(self.user, self.id)
            self.history.clear()
            self.last_intent = None
            self.focus = []
            self.flow = self.calc = self.pending = None
            self.inventory_flow = self.pending_inventory = None
            self.memory = None
            self.clarifications = self.failures = 0
            reply = "Conversation context cleared."
        elif command.name == "/cancel":
            self.inventory_flow = None
            self.pending_inventory = None
            reply = "The current inventory update was cancelled. Nothing was saved."
        elif command.name == "/inventory":
            if command.argument.lower() not in ("", "show"):
                reply = "Use /inventory to add or update cards and EMIs, or /inventory show to view saved items."
                turn = Turn(text=reply, kind="command", agent="general", judge=False, prechecked=True)
                trace.add("command", name="/inventory")
                return await self._deliver(turn, None, command.name, lang, trace)
            action = "show" if command.argument.lower() == "show" else "update"
            if not consent.is_active(self.user.subject, "conversation"):
                self.pending_inventory = (action, lang)
                turn = Turn(text="Please review the conversation permission first. I will then ask separately before saving financial details.",
                            kind="ask", agent="general", judge=False, prechecked=True, request_consent="conversation")
                trace.add("command", name=command.name)
                return await self._deliver(turn, None, command.name, lang, trace)
            if not consent.is_active(self.user.subject, "financial_profile"):
                self.pending_inventory = (action, lang)
                from financial import inventory as inventory_store
                await inventory_store.forget(self.user.id)
                turn = Turn(text="Please review the financial inventory permission on your screen before I continue.",
                            kind="ask", agent="general", judge=False, prechecked=True, request_consent="financial_profile")
            else:
                self.pending_inventory = None
                turn = await self._inventory_action(action, lang, trace)
            trace.add("command", name=command.name)
            return await self._deliver(turn, None, command.name, lang, trace)
        else:
            try:
                summary = await usage_ledger.summary(self.user.id)
                searches = summary.get("calls_by_kind", {}).get("websearch", 0)
                credits = summary.get("units_by_kind", {}).get("websearch", 0)
                reply = (f"Usage this month: ${summary['spent_usd']:.4f} of ${summary['budget_usd']:.2f}; "
                         f"${summary['remaining_usd']:.4f} remaining. {summary['model_calls']} model calls; "
                         f"{summary['tokens']['input'] + summary['tokens']['output']} tokens; {searches} web searches "
                         f"({credits:g} Firecrawl credits). "
                         f"Resets {summary['period']['resets_at'][:10]} UTC. Estimates only.")
            except Exception:
                reply = "Usage is temporarily unavailable. Try again shortly."
        trace.add("command", name=command.name if command.name in commands.COMMANDS else "unknown")
        turn = Turn(text=reply, kind="command", agent="general", judge=False, prechecked=True)
        await self._deliver(turn, None, command.name, lang, trace, persist=command.name not in ("/usage", "/help", "/language", "/clear", "/cancel"))

    async def _inventory_action(self, action: str, lang: str, trace: Trace, initial_request: Optional[str] = None) -> Turn:
        from financial import inventory as inventory_store
        if not consent.is_active(self.user.subject, "financial_profile"):
            await inventory_store.forget(self.user.id)
            return Turn(text="Please review the financial inventory permission on your screen before I continue.",
                        kind="ask", agent="general", judge=False, prechecked=True, request_consent="financial_profile")
        if action == "show":
            items = await inventory_store.list_for(self.user.id)
            return Turn(text="Here is your saved financial inventory.", kind="command", agent="general", judge=False,
                        prechecked=True, card={"type": "financial_inventory", "items": items})
        from financial.inventory_flow import InventoryFlow
        self.inventory_flow, turn = await InventoryFlow.begin(self.user.id, self.user.subject, lang, initial_request)
        return turn

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
        await procedural.refresh()               # procedural memory: this tenant's active prompts and workflows
        trace.add("procedures", versions=procedural.versions())
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
            if self.history and consent.is_active(self.user.subject, "conversation"):
                await working.save(self.user, self.id, self.snapshot())   # working memory: resumable from here

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
        inventory_active = bool(self.inventory_flow and self.inventory_flow.active)
        trace.add("stt", language=lang, transcript="[withheld: financial inventory details]" if inventory_active else text)
        if not text:
            return await self._error("I didn't catch that.")
        await self.ws.send_json({"type": "user", "text": text})
        if inventory_active or not await self._escalated(text, lang, trace):
            await self._respond(text, lang, trace)

    # ---------- deciding what to say: the graph ----------
    async def _recall(self, text: str) -> None:
        """Semantic memory: the remembered facts and past conversations that bear on this question."""
        if consent.is_active(self.user.subject, "memory"):
            recalled = await semantic.recall(self.user.id, text)
            if recalled:
                self.memory = recalled

    async def _respond(self, text: str, lang: str, trace: Trace) -> None:
        await self._status("thinking")
        if not (self.inventory_flow and self.inventory_flow.active):
            await self._recall(text)
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
    async def _deliver(self, turn: Turn, problem: Optional[str], text: str, lang: str, trace: Trace,
                       persist: bool = True) -> None:
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

        # The history feeds hand-off packets, so personal answers are replaced by a placeholder.
        remembered_user = "[gave personal details]" if turn.sensitive_input else text
        remembered_reply = "[read back the person's details]" if turn.kind == "confirm" else guardrails.strip_citations(shown)
        if persist:
            self.history = (self.history + [
                {"role": "user", "content": remembered_user, "intent": self.last_intent},
                {"role": "assistant", "content": remembered_reply},
            ])[-MAX_MESSAGES:]

        if turn.card:  # structured data is deterministic, so it is shown even if the narration was blocked
            if "plans" in turn.card:  # what "the first one" means in the next question
                self.focus = [p.get("product_id") or p["id"] for p in turn.card["plans"]]
            await self.ws.send_json({"type": "card", "kind": turn.kind, "card": turn.card, "trace_id": trace.id})
        structured = structure.build(spoken, turn.append, {} if problem else turn.sources, turn.kind)
        await self.ws.send_json({
            "type": "assistant", "agent": turn.agent, "text": shown, "trace_id": trace.id,
            "citations": structured["sources"],
            "structured": structured,
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

        if persist:
            self._turns += 1
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
        if not consent.is_active(subject, "financial_profile"):
            self.inventory_flow = None
        if not consent.is_active(subject, "conversation"):
            self.pending_inventory = None
            if self.history:
                import asyncio
                asyncio.get_event_loop().create_task(working.drop(self.user, self.id))   # nothing left to resume
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
        from desk import live as desk_live
        return {"id": self.case["id"], "reference": self.case["reference"], "kind": self.case["kind"],
                "status": "with_executive" if self.case["status"] == "assigned" else "waiting",
                "priority": self.case["priority"], "executives_online": bool(desk_live.executives.get(self.user.tenant_id))}

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
        if event["type"] == "inbox":   # a new offer: shown whatever the conversation is doing
            return await self.ws.send_json(event)
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
