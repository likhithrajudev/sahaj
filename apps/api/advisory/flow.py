"""The needs-analysis conversation: collect, confirm, then (and only then) recommend.

    collecting --(everything known)--> confirming --(person says yes)--> recommend --> done

The model phrases questions and reads details back. What gets asked, what is accepted as an answer, and whether
a recommendation may be made at all are decided in code (profile.py, engine.py).
"""
from typing import Dict, Optional, Tuple

from advisory import extract
from advisory.catalogue import is_sample
from advisory.disclosures import VERSION as DISCLOSURES_VERSION
from advisory.disclosures import disclosures
from advisory.engine import AdvisoryRefused, Recommendation, recommend
from advisory.profile import Profile
from agents.base import SUMMARISE, SUMMARISE_ONE, generate
from trust import guardrails
from orchestrator.turn import Turn
from trust import ledger

ROLE = "insurance advisor"
TRIES = 3  # attempts at a read-back or summary before falling back to fixed text
MAX_MISSES = 3  # turns in a row without progress before a person is offered
CONFIRM = ("Read back EVERY detail in the summary, leaving none out, in short sentences, then ask whether that is "
           "right or whether anything should change. Put the source tag right after the details, before the question.")
NO_PLANS = "Tell the user in at most three short sentences what the facts say."

ASK_FALLBACK = {"en-IN": "Sorry, could you say that again?", "hi-IN": "माफ़ कीजिए, क्या आप दोबारा बता सकते हैं?"}
CONFIRM_FALLBACK = {"en-IN": "Sorry, I couldn't read that back properly. Let me try again.",
                    "hi-IN": "माफ़ कीजिए, मैं इसे ठीक से दोहरा नहीं पाया। मैं फिर कोशिश करता हूँ।"}
RECOMMEND_FALLBACK = {"en-IN": "Here are the options that match what you told me. Please see the details on your screen.",
                      "hi-IN": "आपकी बताई जानकारी के अनुसार ये विकल्प हैं। विवरण अपनी स्क्रीन पर देखें।"}
STUCK = {"en-IN": "I'm having trouble understanding that. Let me connect you to a person who can help.",
         "hi-IN": "मुझे यह समझने में कठिनाई हो रही है। मैं आपको किसी ऐसे व्यक्ति से जोड़ता हूँ जो मदद कर सके।"}
REFUSED = {"en-IN": "I can explain and compare plans, but I can't make recommendations right now. I can connect you to a person.",
           "hi-IN": "मैं योजनाओं को समझा और तुलना कर सकता हूँ, पर अभी सिफ़ारिश नहीं कर सकता। मैं आपको किसी व्यक्ति से जोड़ सकता हूँ।"}


def _pick(table: dict, lang_code: str) -> str:
    return table.get(lang_code, table["en-IN"])


class AdviceFlow:
    def __init__(self, subject: str):
        self.subject = subject
        self.profile = Profile()
        self.state = "collecting"   # collecting | confirming | done
        self.asking: Optional[str] = None
        self._lc = "en-IN"
        self._gave_details = False
        self.reconfirm = False  # a read-back was blocked, so the next thing they say should bring it back
        self.misses = 0         # turns in a row that taught us nothing

    @property
    def active(self) -> bool:
        return self.state in ("collecting", "confirming")

    async def handle(self, text: str, lang_code: str, language: str, consent_ok: bool, trace,
                     force: bool = False) -> Optional[Turn]:
        """React to what the person said. With force=False, returns None if it was not an answer to the flow
        (so the caller can treat it as an ordinary question); with force=True it always answers.
        A turn built from personal details is marked so the session keeps the details out of its records."""
        self._lc = lang_code
        self._gave_details = False
        turn = await self._handle(text, language, consent_ok, trace, force)
        if turn is not None:
            turn.sensitive_input = self._gave_details
        return turn

    async def _handle(self, text: str, language: str, consent_ok: bool, trace, force: bool) -> Optional[Turn]:
        if self.state == "done":
            if not force:
                return None
            self.state, self.profile.confirmed = "collecting", False  # a new request: re-confirm what we hold

        before = dict(self.profile.values)
        extracted = await extract.extract(text, self.profile, self.asking)
        extract.apply(self.profile, extracted)
        changed = self.profile.values != before
        self._gave_details = bool(extracted)
        trace.add("advice_extract", fields=sorted(extracted), changed=changed, state=self.state)  # names only

        # Any progress clears the count, however the message arrived. (The first, unforced, look at a message only
        # decides whether it was an answer, so only the forced second look can count as a miss.)
        if changed:
            self.misses = 0
        elif force:
            self.misses += 1
        if force and self.misses >= MAX_MISSES and self.state != "done":
            self.misses = 0
            return Turn(text=_pick(STUCK, self._lc), kind="ask", agent="advice", judge=False, handoff_after=True)

        if self.reconfirm and self.profile.complete():
            self.reconfirm = False
            return await self._confirm(language)

        if self.state == "confirming" and not changed:
            verdict = await extract.agrees(text)
            trace.add("advice_confirm_reply", verdict=verdict)
            if verdict is True:
                self.profile.confirmed = True
                return await self._recommend(language, consent_ok, trace)
            if verdict is False:
                self.state, self.asking = "collecting", None
                return await self._ask("ask what they would like to correct, in their own words", language)
            return await self._confirm(language) if force else None

        if self.asking == "priorities" and not changed and not force and "?" not in text and len(text.split()) <= 8:
            self.profile.set("priorities", [])  # a short answer that names nothing: nothing in particular matters
            changed = True
        if not changed and not force:
            return None
        if self.asking == "priorities":
            self.profile.asked_optional = True  # the question was put to them, whatever the answer
        return await self._next(language)

    async def _narrate(self, sources: Dict[str, str], request: str, language: str, depth: str, asked: str,
                       advice: bool = False) -> Tuple[str, bool]:
        """Words for `sources`, checked with the guardrails, retried if blocked. (text, passed)."""
        text = ""
        for _ in range(TRIES):
            text = await generate(ROLE, sources, request, None, language, depth, advice=advice)
            if guardrails.check_reply(text, sources, advice) is None and \
                    await guardrails.is_grounded(text, sources, asked, True):
                return text, True
        return text, False

    # ---------------------------------------------------------------- steps
    async def _next(self, language: str) -> Turn:
        missing = self.profile.next_missing()
        if missing is None:
            return await self._confirm(language)
        self.asking = missing.name
        turn = await self._ask(f"ask the user {self.profile.question_for(missing)}", language)
        progress = self.profile.progress()
        if progress:  # the question being asked is number answered + 1
            turn.progress = (min(progress[0] + 1, progress[1]), progress[1])
        return turn

    async def _ask(self, instruction: str, language: str) -> Turn:
        return Turn(text=await extract.phrase(instruction, language), kind="ask", agent="advice", judge=False,
                    fallback=_pick(ASK_FALLBACK, self._lc))

    async def _confirm(self, language: str) -> Turn:
        self.state, self.asking = "confirming", None
        sources = {"profile:summary": self.profile.summary()}
        asked = "Read the person's details back accurately."
        text, passed = await self._narrate(sources, "Read my details back to me.", language, CONFIRM, asked)

        def revert():  # never heard, so they must not be asked to confirm it: read it back again on their next turn
            self.state, self.reconfirm = "collecting", True

        # The complete details are also sent as data, so a spoken read-back that leaves something out cannot be
        # "confirmed" unseen. The screen shows exactly what will be used.
        card = {"type": "profile_summary", "details": sources["profile:summary"].rstrip(".").split("; ")}
        total = (self.profile.progress() or (0, 0))[1]
        return Turn(text=text, kind="confirm", agent="advice", sources=sources, detailed=True, asked=asked, card=card,
                    fallback=_pick(CONFIRM_FALLBACK, self._lc), on_blocked=revert, prechecked=passed,
                    progress=(total, total) if total else None)

    async def _recommend(self, language: str, consent_ok: bool, trace) -> Turn:
        try:
            rec = recommend(self.profile, consent_ok=consent_ok)
        except AdvisoryRefused as refused:
            trace.add("advice_refused", reason=refused.reason)
            self.state = "done"
            return Turn(text=_pick(REFUSED, self._lc), kind="answer", agent="advice", judge=False)

        record = ledger.append("recommendation", self.subject, {
            **rec.audit, "disclosures_version": DISCLOSURES_VERSION, "language": self._lc, "consent": "needs_analysis",
        }, trace.id)
        trace.add("recommendation", ledger_seq=record["seq"], plans=[i["product_id"] for i in rec.items],
                  rules_version=rec.audit["rules_version"])
        self.state = "done"

        asked = "Summarise the suggested cover and the top-ranked plan."
        depth = (SUMMARISE if len(rec.items) > 1 else SUMMARISE_ONE) if rec.items else NO_PLANS
        text, passed = await self._narrate(rec.facts, "Tell me what you suggest.", language, depth, asked, advice=True)
        return Turn(text=text, kind="recommendation", agent="advice", sources=rec.facts, allow_recommendation=True,
                    detailed=True, asked=asked, card=self._card(rec), fallback=_pick(RECOMMEND_FALLBACK, self._lc),
                    append=disclosures(self._lc)[:2], prechecked=passed)

    def _card(self, rec: Recommendation) -> dict:
        keep = ("rank", "product_id", "name", "insurer", "cover", "annual_premium", "highlights", "reasons",
                "meets_suggested_cover")
        return {
            "type": "recommendation", "goal": rec.goal, "sample_data": is_sample(), "indicative_premiums": True,
            "suggested_cover": {"amount": rec.cover["need"], "basis": rec.cover["basis"], "note": rec.cover.get("note")},
            "plans": [{**{k: i[k] for k in keep}, "criteria": i["breakdown"]} for i in rec.items],
            "disclosures": disclosures(self._lc), "disclosures_version": DISCLOSURES_VERSION,
        }
