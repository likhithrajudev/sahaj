"""Ephemeral conversational intake for a person's private financial inventory."""
import json
import re
from typing import Optional

from advisory.extract import phrase
from advisory.profile import bare_answer, parse_int, parse_money
from financial import inventory
from financial.inventory_schema import CreditCardRecord, LoanRecord
from orchestrator.turn import Turn
from services.chat import chat
from trust import consent


EXTRACT = """Extract only credit card or loan details the person explicitly stated.
Return JSON only: {{"items": [...]}}.
For credit cards each item has label, last_four, outstanding_balance, minimum_due, due_day,
annual_interest_rate_percent, and evidence (an exact quote from the message for the values).
For loans each item has label, monthly_emi, outstanding_principal, due_day,
annual_interest_rate_percent, remaining_months, and evidence (an exact quote from the message for the values).
Use null for any unknown optional value. Never infer, invent, combine two accounts, or turn a monthly rate into an annual rate.
Money is whole rupees. Rate is an annual percentage. Keep card last_four to four digits only.
Kind: {kind}
Message: {message}"""

MAX_ITEMS = 20


class InventoryFlow:
    def __init__(self, user_id: str, subject: str, cards: list[dict], loans: list[dict]):
        self.user_id = user_id
        self.subject = subject
        self.cards = cards
        self.loans = loans
        self.active = True
        self.stage = "cards_choice"
        self.attempts = 0
        self.loans_from_initial = False
        self.lang = "en-IN"

    @property
    def asking(self) -> str:
        return self.stage

    @classmethod
    async def begin(cls, user_id: str, subject: str, lang: str, initial_request: Optional[str] = None) -> tuple["InventoryFlow", Turn]:
        current = await inventory.list_for(user_id)
        cards = [{"label": item["label"], **item["details"]} for item in current if item["type"] == "credit_card"]
        loans = [{"label": item["label"], **item["details"]} for item in current if item["type"] == "loan"]
        flow = cls(user_id, subject, cards, loans)
        flow.lang = lang
        wants_cards = bool(initial_request and re.search(r"credit.?card|card|क्रेडिट.?कार्ड|कार्ड", initial_request, re.I))
        wants_loans = bool(initial_request and re.search(r"loan|emi|लोन|ईएमआई|किस्त", initial_request, re.I))
        if initial_request and _contains_secret(initial_request):
            flow.stage = "cards_details" if wants_cards else "loans_details"
            return flow, await flow._ask("Tell the person not to send a CVV, security code, PIN or password. Ask them to resend only the card or loan details Sahaj requested.")
        if wants_cards and re.search(r"(?<!\d)(?:\d[ -]?){11,18}\d(?!\d)", initial_request):
            flow.stage = "cards_details"
            return flow, await flow._ask("Tell the person the full card number was not accepted. Ask them to resend details with last four digits only and never send a CVV or PIN.")
        if wants_cards or wants_loans:
            card_rows, loan_rows = [], []
            if wants_cards:
                try:
                    card_rows = await _extract("credit_card", initial_request)
                except Exception:
                    card_rows = None
            if wants_loans:
                try:
                    loan_rows = await _extract("loan", initial_request)
                except Exception:
                    loan_rows = None
            if card_rows:
                flow.cards = card_rows
            if loan_rows:
                flow.loans = loan_rows
                flow.loans_from_initial = True
            if (not wants_cards or card_rows) and (not wants_loans or loan_rows):
                return flow, await flow._confirm()
            if wants_cards and not card_rows:
                flow.stage = "cards_details"
                return flow, await flow._ask("Ask for each card's label, last four digits only, outstanding balance, minimum due, due day of the month and annual interest rate if known. Warn not to send the full card number, CVV or PIN.")
            if wants_loans and not loan_rows:
                flow.stage = "loans_details"
                return flow, await flow._ask("Ask for each loan's label or lender, monthly EMI, outstanding principal, due day, annual interest rate and remaining months if known.")
        if wants_cards:
            flow.stage = "cards_details"
            return flow, await flow._ask("Ask for each card's label, last four digits only, outstanding balance, minimum due, due day of the month and annual interest rate if known. Warn not to send the full card number, CVV or PIN.")
        if wants_loans:
            flow.stage = "loans_details"
            return flow, await flow._ask("Ask for each loan's label or lender, monthly EMI, outstanding principal, due day, annual interest rate and remaining months if known.")
        return flow, await flow._ask("Ask whether the person has credit cards to add or update. Tell them that no keeps saved cards.")

    async def handle(self, text: str, lang: str) -> Turn:
        self.lang = lang or self.lang
        value = text.strip()
        if _contains_secret(value):
            return await self._ask("Tell the person not to send a CVV, security code, PIN or password. Ask them to resend only the card or loan details requested.")
        if self.stage in ("cards_choice", "cards_details") and re.search(r"(?<!\d)(?:\d[ -]?){11,18}\d(?!\d)", value):
            return await self._ask("Tell the person the full card number was not accepted. Ask them to resend details with last four digits only and never send a CVV or PIN.")
        if value.lower() in ("cancel", "stop", "/cancel") or value in ("रद्द", "बंद करें"):
            self.active = False
            return Turn(text=await phrase("confirm that the inventory update was cancelled and nothing was saved", lang),
                        kind="command", agent="general", judge=False, prechecked=True, sensitive_input=True)
        if self.stage in ("cards_choice", "loans_choice"):
            answer = bare_answer(value)
            if answer is None:
                return await self._ask("Ask for a clear yes or no. A no keeps the currently saved items in this category.")
            if self.stage == "cards_choice":
                if answer:
                    self.stage = "cards_details"
                    self.attempts = 0
                    return await self._ask("Ask for each card's label, last four digits only, outstanding balance, minimum due, due day of the month and annual interest rate if known. Warn not to send the full card number, CVV or PIN.")
                return await self._ask_loans()
            if answer:
                self.stage = "loans_details"
                self.attempts = 0
                return await self._ask("Ask for each loan's label or lender, monthly EMI, outstanding principal, due day, annual interest rate and remaining months if known.")
            return await self._confirm()
        if self.stage in ("cards_details", "loans_details"):
            kind = "credit_card" if self.stage == "cards_details" else "loan"
            if bare_answer(value) is False:
                self._set_items(kind, [])
                return await self._after_cards() if kind == "credit_card" else await self._confirm()
            try:
                parsed = await _extract(kind, value)
            except Exception:
                parsed = []
            if parsed is None or not parsed:
                self.attempts += 1
                if self.attempts < 3:
                    return await self._ask("Ask the person to retry with one account per line and clearly label each amount, due day and annual rate. Do not ask them to send full card numbers or security codes.")
                self.stage = "loans_choice" if kind == "credit_card" else "confirm"
                return await self._after_cards() if kind == "credit_card" else await self._confirm()
            self._set_items(kind, parsed)
            return await self._after_cards() if kind == "credit_card" else await self._confirm()
        if self.stage == "confirm":
            answer = bare_answer(value)
            if answer is not True:
                self.active = False
                return Turn(text=await phrase("say the inventory was not changed because the person did not confirm saving it", lang),
                            kind="command", agent="general", judge=False, prechecked=True, sensitive_input=True)
            if not consent.is_active(self.subject, "financial_profile"):
                self.active = False
                return Turn(text=await phrase("say that financial inventory consent is no longer active, so nothing was saved", lang),
                            kind="command", agent="general", judge=False, prechecked=True, sensitive_input=True,
                            request_consent="financial_profile")
            saved = await inventory.replace_for(self.user_id, self.cards, self.loans)
            self.active = False
            return Turn(text=await phrase("confirm that the reviewed financial inventory is saved and can be viewed with /inventory show", lang),
                        kind="command", agent="general", judge=False, prechecked=True, sensitive_input=True,
                        card={"type": "financial_inventory", "items": saved})
        return await self._confirm()

    def _set_items(self, kind: str, items: list[dict]) -> None:
        if kind == "credit_card":
            self.cards = items
        else:
            self.loans = items

    async def _ask_loans(self) -> Turn:
        self.stage = "loans_choice"
        self.attempts = 0
        return await self._ask("Ask whether the person has active loans or EMIs to add or update. A no keeps saved loans.")

    async def _after_cards(self) -> Turn:
        return await self._confirm() if self.loans_from_initial else await self._ask_loans()

    async def _ask(self, instruction: str) -> Turn:
        return Turn(text=await phrase(instruction, self.lang), kind="ask", agent="general", judge=False,
                    prechecked=True, sensitive_input=True)

    async def _confirm(self) -> Turn:
        self.stage = "confirm"
        rows = [{"type": "credit_card", **item} for item in self.cards]
        rows += [{"type": "loan", **item} for item in self.loans]
        summary = "Review your financial inventory below. Reply yes to save it, or no to discard these changes."
        if not rows:
            summary = "Your reviewed financial inventory is empty. Reply yes to save the empty inventory, or no to cancel."
        return Turn(text=summary, kind="confirm", agent="general", judge=False, prechecked=True, sensitive_input=True,
                    card={"type": "financial_inventory_review", "items": rows})


async def _extract(kind: str, text: str) -> Optional[list[dict]]:
    raw = await chat([{"role": "system", "content": EXTRACT.format(kind=kind, message=text)},
                      {"role": "user", "content": "Extract only the stated accounts as JSON."}], purpose="extract")
    try:
        payload = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        rows = payload.get("items")
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        return None
    output = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        evidence = row.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip() or _norm(evidence) not in _norm(text):
            return None
        label = row.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 100 or _norm(label) not in _norm(text):
            return None
        item = {"label": label.strip()}
        if kind == "credit_card":
            last_four = row.get("last_four")
            if last_four is not None and (not re.fullmatch(r"\d{4}", str(last_four)) or str(last_four) not in text):
                return None
            balance = _money(row.get("outstanding_balance"), row.get("balance_evidence"), text)
            minimum = _money(row.get("minimum_due"), row.get("minimum_due_evidence"), text)
            due_day = _integer(row.get("due_day"), row.get("due_day_evidence"), text, 1, 31)
            rate = _rate(row.get("annual_interest_rate_percent"), row.get("rate_evidence"), text, 100)
            if balance is None:
                return None
            if row.get("minimum_due") is not None and minimum is None:
                return None
            if row.get("due_day") is not None and due_day is None:
                return None
            if row.get("annual_interest_rate_percent") is not None and rate is None:
                return None
            item.update(outstanding_balance=balance, minimum_due=minimum, due_day=due_day,
                        annual_interest_rate_percent=rate)
            if last_four is not None:
                item["last_four"] = str(last_four)
        else:
            emi = _money(row.get("monthly_emi"), row.get("emi_evidence"), text)
            principal = _money(row.get("outstanding_principal"), row.get("principal_evidence"), text)
            due_day = _integer(row.get("due_day"), row.get("due_day_evidence", evidence), text, 1, 31)
            rate = _rate(row.get("annual_interest_rate_percent"), row.get("rate_evidence", evidence), text, 60)
            months = _integer(row.get("remaining_months"), row.get("remaining_months_evidence", evidence), text, 0, 600)
            if emi is None or principal is None:
                return None
            if row.get("due_day") is not None and due_day is None:
                return None
            if row.get("annual_interest_rate_percent") is not None and rate is None:
                return None
            if row.get("remaining_months") is not None and months is None:
                return None
            item.update(monthly_emi=emi, outstanding_principal=principal, due_day=due_day,
                        annual_interest_rate_percent=rate, remaining_months=months)
        try:
            validated = CreditCardRecord.model_validate(item) if kind == "credit_card" else LoanRecord.model_validate(item)
        except ValueError:
            return None
        output.append(validated.model_dump(exclude_none=True))
    return output


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_secret(text: str) -> bool:
    return bool(re.search(r"\b(?:cvv|cvc|security code|pin|password)\b\D*\d{3,}", text, re.I))


def _evidence(value, evidence, text) -> bool:
    return value is None or (isinstance(evidence, str) and bool(evidence.strip()) and _norm(evidence) in _norm(text))


def _money(value, evidence, text):
    if value is None:
        return None
    if not _evidence(value, evidence, text) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = parse_money(evidence)
    return int(value) if parsed == int(value) and 0 <= int(value) <= 1_000_000_000 else None


def _integer(value, evidence, text, low, high):
    if value is None:
        return None
    if not _evidence(value, evidence, text) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = parse_int(evidence)
    return int(value) if parsed == int(value) and low <= int(value) <= high else None


def _rate(value, evidence, text, maximum):
    if value is None:
        return None
    if not _evidence(value, evidence, text) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", evidence, re.I)
    if not match:
        return None
    rate = float(match.group(1))
    return rate if abs(rate - float(value)) < 0.001 and 0 <= rate <= maximum else None
