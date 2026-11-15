import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loan import calc, flow


def emi_by_bisection(principal, annual_rate, months):
    """An independent way to find the EMI: search for the payment that leaves exactly nothing owed."""
    r = annual_rate / 12 / 100
    lo, hi = 0.0, principal * 2
    for _ in range(200):
        mid = (lo + hi) / 2
        balance = principal
        for _ in range(months):
            balance = balance * (1 + r) - mid
        lo, hi = (mid, hi) if balance > 0 else (lo, mid)
    return (lo + hi) / 2


@pytest.mark.parametrize("principal, rate, months", [(100_000, 12, 12), (500_000, 11, 36), (2_500_000, 8.5, 240), (300_000, 0.1, 24)])
def test_emi_matches_an_independent_calculation(principal, rate, months):
    assert calc.emi(principal, rate, months) == pytest.approx(emi_by_bisection(principal, rate, months), rel=1e-6)


def test_known_value():
    assert calc.summary(100_000, 12, 12)["emi"] == 8885  # the standard textbook figure (8884.88)


def test_zero_rate_is_plain_division():
    assert calc.emi(120_000, 0, 12) == 10_000


def test_total_interest_is_total_payment_minus_principal():
    s = calc.summary(500_000, 11, 36)
    assert s["total_payment"] - 500_000 == s["total_interest"]


def test_prepaying_always_saves_interest_and_reduce_tenure_saves_more():
    shorter = calc.prepayment(500_000, 11, 36, 100_000, "reduce_tenure")
    lower = calc.prepayment(500_000, 11, 36, 100_000, "reduce_emi")
    assert shorter["interest_saved"] > 0 and lower["interest_saved"] > 0
    assert shorter["months_after"] < shorter["months_before"] and lower["months_after"] == lower["months_before"]
    assert shorter["interest_saved"] > lower["interest_saved"]   # same money, finishes sooner, so less interest
    assert lower["emi_after"] < lower["emi_before"]


@pytest.mark.parametrize("prepay", [0, -5, 500_000, 600_000])
def test_impossible_prepayments_are_refused(prepay):
    with pytest.raises(ValueError):
        calc.prepayment(500_000, 11, 36, prepay)


# ---- reading the numbers: every value must be backed by the person's own words
@pytest.mark.parametrize("name, item, text, expected", [
    ("principal", {"value": 500000, "evidence": "5 lakh"}, "emi on 5 lakh please", 500000),
    ("principal", {"value": 50000000, "evidence": "5 lakh"}, "emi on 5 lakh please", None),          # unit slip: 5 lakh != 5 crore
    ("principal", {"value": 500000, "evidence": "5 lakh"}, "emi on 8 lakh please", None),             # quote not said
    ("annual_rate_percent", {"value": 11, "evidence": "11 percent"}, "at 11 percent", 11),
    ("annual_rate_percent", {"value": 11, "evidence": "11"}, "at 11 for 3 years", None),               # no sign it is a rate
    ("annual_rate_percent", {"value": 12, "evidence": "11 percent"}, "at 11 percent", None),
    ("tenure_months", {"value": 36, "evidence": "3 years"}, "over 3 years", 36),
    ("tenure_months", {"value": 3, "evidence": "3 years"}, "over 3 years", None),                      # years left as months
    ("tenure_months", {"value": 18, "evidence": "18 months"}, "for 18 months", 18),
    ("tenure_months", {"value": 36, "evidence": "3 साल"}, "3 साल के लिए", 36),
    ("mode", {"value": "reduce_emi", "evidence": "lower the emi"}, "I want to lower the emi", "reduce_emi"),
    ("mode", {"value": "forever", "evidence": "x"}, "x", None),
])
def test_values_need_the_persons_own_words(name, item, text, expected):
    assert flow.verified(name, item, text) == expected


def test_calculator_asks_only_for_what_is_missing_then_answers(monkeypatch):
    answers = iter([{"principal": 500000}, {"annual_rate_percent": 11, "tenure_months": 36}])

    async def fake_extract(text):
        return next(answers)

    async def fake_phrase(instruction, language):
        return "ASK: " + instruction

    async def fake_generate(role, sources, request, previous, language, depth, advice=False):
        return "RESULT " + " ".join(sources.values())
    monkeypatch.setattr(flow, "extract", fake_extract)
    monkeypatch.setattr(flow, "phrase", fake_phrase)
    monkeypatch.setattr(flow, "generate", fake_generate)

    async def scenario():
        c = flow.LoanCalc()
        first = await c.handle("emi on 5 lakh", "en-IN", "English", force=True)
        second = await c.handle("11 percent for 3 years", "en-IN", "English")
        return first, second, c
    first, second, c = asyncio.run(scenario())
    assert first.kind == "ask" and "interest rate" in first.text and "loan amount" not in first.text
    assert second.kind == "calc" and "16,369" in second.text and second.card["result"]["emi"] == 16369
    assert second.sensitive_input and not c.active


def test_numbers_that_cannot_work_are_explained_not_computed(monkeypatch):
    async def fake_extract(text):
        return {"principal": 100000, "annual_rate_percent": 10, "tenure_months": 12, "prepay_amount": 100000}

    async def fake_phrase(instruction, language):
        return "ASK: " + instruction
    monkeypatch.setattr(flow, "extract", fake_extract)
    monkeypatch.setattr(flow, "phrase", fake_phrase)
    turn = asyncio.run(flow.LoanCalc().handle("prepay everything", "en-IN", "English", force=True))
    assert turn.kind == "ask" and "do not work" in turn.text


def test_calculator_gives_up_politely_after_repeated_misses(monkeypatch):
    async def nothing(text):
        return {}

    async def fake_phrase(instruction, language):
        return "ASK"
    monkeypatch.setattr(flow, "extract", nothing)
    monkeypatch.setattr(flow, "phrase", fake_phrase)

    async def scenario():
        c = flow.LoanCalc()
        return [await c.handle("blah", "en-IN", "English", force=True) for _ in range(flow.MAX_MISSES)]
    turns = asyncio.run(scenario())
    assert [t.handoff_after for t in turns] == [False, False, True]


def test_prepayment_sentence_is_well_formed(monkeypatch):
    async def fake_extract(text):
        return {"principal": 500000, "annual_rate_percent": 11, "tenure_months": 36, "prepay_amount": 100000}

    async def fake_generate(role, sources, request, previous, language, depth, advice=False):
        return " ".join(sources.values())
    monkeypatch.setattr(flow, "extract", fake_extract)
    monkeypatch.setattr(flow, "generate", fake_generate)
    turn = asyncio.run(flow.LoanCalc().handle("prepay 1 lakh", "en-IN", "English", force=True))
    assert "Rs Rs" not in turn.text and "saving of Rs 34,351" in turn.text and turn.card["kind"] == "prepayment"
