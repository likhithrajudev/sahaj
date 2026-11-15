"""Financial inventory stays private, consent-gated and explicitly confirmed."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.deps import current_user
from auth.store import User
from financial import inventory as inventory_store
from financial.inventory_flow import InventoryFlow, _extract
from financial.inventory_schema import InventoryReplacement
from main import app
from orchestrator.session import _inventory_request
from trust import consent

USER = User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
            language="en-IN", platform="web", role="user")


def test_inventory_schema_rejects_full_card_number_and_extra_fields():
    base = {"credit_cards": [], "loans": [], "confirmed": True}
    with pytest.raises(ValueError):
        InventoryReplacement.model_validate({**base, "credit_cards": [{"label": "Card", "last_four": "12345",
                                                                          "outstanding_balance": 1000}]})
    with pytest.raises(ValueError):
        InventoryReplacement.model_validate({**base, "credit_cards": [{"label": "Card", "card_number": "1234",
                                                                          "outstanding_balance": 1000}]})
    with pytest.raises(ValueError):
        InventoryReplacement.model_validate({**base, "credit_cards": [{"label": "Card 1234567890123456",
                                                                          "outstanding_balance": 1000}]})


def test_plain_language_inventory_request_is_recognized():
    assert _inventory_request("Please track my credit card due dates and EMI")
    assert _inventory_request("मेरे कार्ड और EMI का हिसाब रखो")
    assert not _inventory_request("What is an EMI?")


def test_flow_keeps_unmodified_category_and_saves_only_after_yes(monkeypatch):
    existing = [{"id": "card-1", "type": "credit_card", "label": "Everyday card",
                 "details": {"last_four": "1234", "outstanding_balance": 5000}}]
    saved = []

    async def list_for(_):
        return existing

    async def replace_for(user_id, cards, loans):
        saved.append((user_id, cards, loans))
        return [{"id": "loan-1", "type": "loan", "label": loans[0]["label"], "details": loans[0]}]

    async def ask(instruction, _language):
        return instruction

    raw = {"items": [{
        "label": "SBI personal loan", "monthly_emi": 15000, "outstanding_principal": 400000,
        "due_day": 5, "annual_interest_rate_percent": 12, "remaining_months": 36,
        "evidence": "SBI personal loan, EMI ₹15,000, outstanding principal ₹4,00,000, due on 5th, annual rate 12%, remaining 36 months",
        "emi_evidence": "EMI ₹15,000", "principal_evidence": "outstanding principal ₹4,00,000",
        "due_day_evidence": "due on 5th", "rate_evidence": "annual rate 12%",
        "remaining_months_evidence": "remaining 36 months",
    }]}

    async def extract_chat(*_, **__):
        return json.dumps(raw)

    monkeypatch.setattr(inventory_store, "list_for", list_for)
    monkeypatch.setattr(inventory_store, "replace_for", replace_for)
    monkeypatch.setattr("financial.inventory_flow.phrase", ask)
    monkeypatch.setattr("financial.inventory_flow.chat", extract_chat)
    monkeypatch.setattr(consent, "is_active", lambda *_: True)

    async def run():
        flow, _ = await InventoryFlow.begin(USER.id, USER.subject, "en-IN")
        await flow.handle("no", "en-IN")
        await flow.handle("yes", "en-IN")
        review = await flow.handle("SBI personal loan, EMI ₹15,000, outstanding principal ₹4,00,000, due on 5th, annual rate 12%, remaining 36 months", "en-IN")
        assert review.kind == "confirm" and len(review.card["items"]) == 2
        assert saved == []
        completed = await flow.handle("yes", "en-IN")
        assert completed.card["type"] == "financial_inventory"
        assert len(saved) == 1 and saved[0][0] == USER.id
        assert saved[0][1][0]["label"] == "Everyday card"
        assert saved[0][2][0]["monthly_emi"] == 15000

    asyncio.run(run())


def test_extractor_rejects_values_without_exact_evidence(monkeypatch):
    async def model(*_, **__):
        return json.dumps({"items": [{"label": "SBI loan", "monthly_emi": 15000, "outstanding_principal": 400000,
                                      "evidence": "SBI loan", "emi_evidence": "EMI ₹12,000",
                                      "principal_evidence": "outstanding ₹4,00,000"}]})

    monkeypatch.setattr("financial.inventory_flow.chat", model)
    assert asyncio.run(_extract("loan", "SBI loan, EMI ₹15,000, outstanding ₹4,00,000")) is None


def test_initial_natural_request_is_processed_into_review_card_after_consent(monkeypatch):
    message = "Track my HDFC card ending 1234, balance ₹50,000, minimum due ₹2,500, due day 12, annual rate 36%."
    model = {"items": [{
        "label": "HDFC card", "last_four": "1234", "outstanding_balance": 50000, "minimum_due": 2500,
        "due_day": 12, "annual_interest_rate_percent": 36,
        "evidence": message, "balance_evidence": "balance ₹50,000", "minimum_due_evidence": "minimum due ₹2,500",
        "due_day_evidence": "due day 12", "rate_evidence": "annual rate 36%",
    }]}

    async def list_for(_):
        return []

    async def model_chat(*_, **__):
        return json.dumps(model)

    async def ask(instruction, _language):
        return instruction

    monkeypatch.setattr(inventory_store, "list_for", list_for)
    monkeypatch.setattr("financial.inventory_flow.chat", model_chat)
    monkeypatch.setattr("financial.inventory_flow.phrase", ask)

    async def run():
        _, turn = await InventoryFlow.begin(USER.id, USER.subject, "en-IN", message)
        assert turn.kind == "confirm"
        item = turn.card["items"][0]
        assert item["last_four"] == "1234" and item["outstanding_balance"] == 50000
        assert item["minimum_due"] == 2500 and item["annual_interest_rate_percent"] == 36

    asyncio.run(run())


def test_inventory_api_requires_active_consent_and_explicit_confirmation(monkeypatch):
    previous = app.dependency_overrides.get(current_user)
    app.dependency_overrides[current_user] = lambda: USER
    calls = []

    async def list_for(user_id):
        calls.append(("list", user_id))
        return [{"id": "card-1", "type": "credit_card", "label": "Card", "details": {}}]

    async def forget(user_id):
        calls.append(("forget", user_id))
        return 1

    async def replace_for(user_id, cards, loans):
        calls.append(("replace", user_id, cards, loans))
        return []

    async def delete_one(user_id, item_id):
        calls.append(("delete", user_id, item_id))
        return user_id == USER.id and item_id == "card-1"

    monkeypatch.setattr(inventory_store, "list_for", list_for)
    monkeypatch.setattr(inventory_store, "forget", forget)
    monkeypatch.setattr(inventory_store, "replace_for", replace_for)
    monkeypatch.setattr(inventory_store, "delete_one", delete_one)
    active = {"value": False}
    monkeypatch.setattr(consent, "is_active", lambda _subject, purpose: active["value"] if purpose == "financial_profile" else True)

    async def run():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                hidden = await client.get("/financial/inventory")
                assert hidden.status_code == 200 and hidden.json()["items"] == [] and calls[-1] == ("forget", USER.id)
                body = {"credit_cards": [], "loans": [], "confirmed": False}
                assert (await client.put("/financial/inventory", json=body)).status_code == 409
                active["value"] = True
                visible = await client.get("/financial/inventory")
                assert visible.status_code == 200 and visible.json()["items"][0]["id"] == "card-1"
                assert calls[-1] == ("list", USER.id)
                body["confirmed"] = True
                assert (await client.put("/financial/inventory", json=body)).status_code == 200
                assert calls[-1] == ("replace", USER.id, [], [])
                assert (await client.delete("/financial/inventory/card-1")).status_code == 204
                assert calls[-1] == ("delete", USER.id, "card-1")
        finally:
            if previous is None:
                app.dependency_overrides.pop(current_user, None)
            else:
                app.dependency_overrides[current_user] = previous

    asyncio.run(run())
