import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from advisory import catalogue, engine, rules
from advisory.engine import AdvisoryRefused, recommend
from advisory.profile import Profile, parse_money
from advisory.rules import CRORE, LAKH


def profile(**values) -> Profile:
    p = Profile()
    for name, value in values.items():
        assert p.set(name, value), f"{name}={value!r} rejected"
    p.asked_optional = True
    p.confirmed = True
    return p


TERM = dict(goal="term", age=34, annual_income=12 * LAKH, dependents=2, existing_life_cover=0, liabilities=0, smoker=False)
HEALTH = dict(goal="health", age=34, annual_income=12 * LAKH, city_tier="metro", members="family", children=2,
              existing_health_source="none", pre_existing=False, maternity_needed=False)


# ---------------- money parsing: a unit mistake must never slip through
@pytest.mark.parametrize("text, rupees", [
    ("12 lakh", 12 * LAKH), ("12 lakhs", 12 * LAKH), ("1.5 crore", 15 * LAKH * 10), ("90,000", 90_000),
    ("₹12,00,000", 12 * LAKH), ("50k", 50_000), ("12 लाख", 12 * LAKH), ("2 करोड़", 2 * CRORE), ("about 7.5 lakh a year", 7_50_000),
])
def test_parse_money(text, rupees):
    assert parse_money(text) == rupees


@pytest.mark.parametrize("text, rupees", [("twelve lakh", 12 * LAKH), ("twenty five lakh", 25 * LAKH), ("two crore", 2 * CRORE),
                                          ("fifty thousand", 50_000)])
def test_parse_money_number_words(text, rupees):
    assert parse_money(text) == rupees


def test_parse_int_and_bare_answers():
    from advisory.profile import bare_answer, parse_int
    assert parse_int("three people") == 3 and parse_int("I am 34") == 34 and parse_int("nobody") is None
    assert bare_answer("No.") is False and bare_answer("yes, yeah") is True and bare_answer("no I do not smoke") is None


def test_parse_money_rejects_no_number():
    assert parse_money("a good salary") is None


# ---------------- the gate: no recommendation without everything in place
def test_recommends_when_everything_is_in_place():
    assert recommend(profile(**TERM), consent_ok=True).items


def test_refuses_without_consent():
    with pytest.raises(AdvisoryRefused) as e:
        recommend(profile(**TERM), consent_ok=False)
    assert e.value.reason == "no_consent"


def test_refuses_when_profile_incomplete():
    p = profile(**{k: v for k, v in TERM.items() if k != "liabilities"})
    with pytest.raises(AdvisoryRefused) as e:
        recommend(p, consent_ok=True)
    assert e.value.reason == "incomplete"


def test_refuses_until_the_person_confirms():
    p = profile(**TERM)
    p.confirmed = False
    with pytest.raises(AdvisoryRefused) as e:
        recommend(p, consent_ok=True)
    assert e.value.reason == "unconfirmed"


def test_any_change_requires_confirming_again():
    p = profile(**TERM)
    p.set("annual_income", 20 * LAKH)
    assert not p.confirmed


def test_refuses_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ADVISORY_ENABLED", False)
    with pytest.raises(AdvisoryRefused) as e:
        recommend(profile(**TERM), consent_ok=True)
    assert e.value.reason == "disabled"


def test_optional_priorities_question_must_still_be_asked():
    p = Profile()
    for k, v in TERM.items():
        p.set(k, v)
    assert p.next_missing().name == "priorities"
    assert not p.complete()


# ---------------- validation
@pytest.mark.parametrize("name, value", [
    ("age", 17), ("age", 71), ("age", True), ("annual_income", 100), ("dependents", -1), ("smoker", "no"),
    ("goal", "car"), ("city_tier", "village"), ("priorities", ["cheapest"]), ("annual_income", "12 lakh"),
])
def test_invalid_values_are_rejected(name, value):
    assert Profile().set(name, value) is False


def test_conditional_questions():
    p = Profile()
    for k, v in dict(goal="health", age=30, annual_income=8 * LAKH, city_tier="metro", members="self_spouse",
                     existing_health_source="personal").items():
        p.set(k, v)
    assert p.next_missing().name == "existing_health_cover"  # asked only because the cover is their own
    p.set("existing_health_cover", 5 * LAKH)
    p.set("pre_existing", False)
    assert p.next_missing().name == "maternity_needed"       # asked only when a spouse is covered
    p.set("maternity_needed", True)
    assert p.next_missing().name == "priorities"


# ---------------- cover sizing
def test_life_cover_follows_the_rule():
    c = engine.life_cover(profile(**TERM))
    assert c["multiple"] == 10 and c["need"] == 12 * LAKH * 10


def test_life_cover_adds_loans_and_subtracts_existing_cover():
    c = engine.life_cover(profile(**{**TERM, "liabilities": 30 * LAKH, "existing_life_cover": 50 * LAKH}))
    assert c["need"] == 12 * LAKH * 10 + 30 * LAKH - 50 * LAKH


def test_no_dependents_lowers_the_multiple():
    assert engine.life_cover(profile(**{**TERM, "dependents": 0}))["multiple"] == 5


def test_multiple_is_capped_by_working_years_left():
    assert engine.life_cover(profile(**{**TERM, "age": 55}))["multiple"] == 5


def test_existing_cover_above_need_means_no_extra_cover():
    rec = recommend(profile(**{**TERM, "existing_life_cover": 5 * CRORE}), consent_ok=True)
    assert rec.cover["need"] == 0 and rec.items == []
    assert "no additional cover" in rec.facts["rec:cover"]


def test_health_cover_by_city_and_family():
    assert engine.health_cover(profile(**HEALTH))["need"] == 20 * LAKH
    solo = {k: v for k, v in HEALTH.items() if k != "children"}
    assert engine.health_cover(profile(**{**solo, "city_tier": "non_metro", "members": "self"}))["need"] == 5 * LAKH


def test_employer_cover_is_not_subtracted_but_is_noted():
    c = engine.health_cover(profile(**{**HEALTH, "existing_health_source": "employer"}))
    assert c["need"] == 20 * LAKH and "employer" in c["note"]


def test_own_health_cover_is_subtracted():
    p = profile(**{**HEALTH, "existing_health_source": "personal", "existing_health_cover": 10 * LAKH})
    assert engine.health_cover(p)["need"] == 10 * LAKH


# ---------------- eligibility and premiums
def test_age_limits_remove_plans():
    assert recommend(profile(**{**TERM, "age": 61}), consent_ok=True).items == []   # all term plans stop at 60


def test_maternity_need_filters_to_plans_that_cover_it():
    rec = recommend(profile(**{**HEALTH, "maternity_needed": True}), consent_ok=True)
    assert [i["product_id"] for i in rec.items] == ["health-peepal-family"]


def test_smoker_pays_more():
    non = recommend(profile(**TERM), consent_ok=True).items[0]["annual_premium"]
    smoker = recommend(profile(**{**TERM, "smoker": True}), consent_ok=True)
    assert min(i["annual_premium"] for i in smoker.items) > non


def test_premium_comes_from_the_catalogue_table():
    rec = recommend(profile(**TERM), consent_ok=True)
    banyan = next(i for i in rec.items if i["product_id"] == "term-banyan-flex")
    rate = catalogue.by_id("term-banyan-flex")["rate_per_crore"]["non_smoker"][2]   # age 34 -> band 31-35
    assert banyan["annual_premium"] == round(rate * banyan["cover"] / CRORE / 10) * 10


def test_health_premium_scales_with_family_size():
    solo = recommend(profile(**{**{k: v for k, v in HEALTH.items() if k != "children"}, "members": "self"}), consent_ok=True)
    fam = recommend(profile(**HEALTH), consent_ok=True)
    pid = "health-lotus-care"
    price = lambda r: next(i for i in r.items if i["product_id"] == pid)["annual_premium"]
    assert price(fam) > price(solo)


def test_plan_below_the_suggested_cover_says_so(monkeypatch):
    monkeypatch.setitem(rules.HEALTH_BASE_SI, "metro", 20 * LAKH)  # family need becomes 40 lakh; Neem tops out at 25 lakh
    rec = recommend(profile(**HEALTH), consent_ok=True)
    neem = next(i for i in rec.items if i["product_id"] == "health-neem-essential")
    assert neem["meets_suggested_cover"] is False
    assert "largest" in rec.facts["rec:health-neem-essential"]


# ---------------- ranking
def test_ranking_is_deterministic():
    a, b = recommend(profile(**TERM), consent_ok=True), recommend(profile(**TERM), consent_ok=True)
    assert [i["product_id"] for i in a.items] == [i["product_id"] for i in b.items]
    assert a.audit["ranked"] == b.audit["ranked"]


def test_stated_priority_changes_the_ranking():
    base = recommend(profile(**HEALTH), consent_ok=True).items
    cheap = recommend(profile(**{**HEALTH, "priorities": ["low_premium"]}), consent_ok=True).items
    weights = lambda r: r[0]["breakdown"]["premium"]["weight"]
    assert weights(cheap) > weights(base)


def test_weights_always_sum_to_one():
    for goal, extra in (("term", ["riders"]), ("health", ["low_waiting", "low_premium"]), ("whole_life", [])):
        assert sum(engine._weights(goal, extra).values()) == pytest.approx(1.0)


def test_never_a_single_best_and_at_most_three():
    items = recommend(profile(**HEALTH), consent_ok=True).items
    assert 1 < len(items) <= 3 and [i["rank"] for i in items] == list(range(1, len(items) + 1))


def test_every_number_in_the_facts_is_traceable():
    rec = recommend(profile(**HEALTH), consent_ok=True)
    top = rec.items[0]
    assert f"{top['annual_premium']:,}".replace(",", "") in rec.facts[f"rec:{top['product_id']}"].replace(",", "")


# ---------------- audit
def test_audit_holds_bands_never_exact_figures():
    p = profile(**{**TERM, "annual_income": 1_234_567, "age": 37, "liabilities": 3_456_789, "existing_life_cover": 2_345_678})
    rec = recommend(p, consent_ok=True)
    blob = str(rec.audit)
    # exact figures in every form they could be written
    for figure in ("1234567", "12,34,567", "3456789", "34,56,789", "2345678", "23,45,678"):
        assert figure not in blob, figure
    assert "'age': 37" not in blob
    assert rec.audit["profile_bands"]["age_band"] == "35-39"
    assert rec.audit["rules_version"] and rec.audit["catalogue_sha256"]
    assert rec.audit["suggested_cover"]["need"] > 0   # the rule's result is kept so the figure can be reproduced


# ---------------- catalogue and wording stay in step
def test_every_product_has_a_wording_document():
    docs = Path(__file__).resolve().parent.parent / "knowledge" / "insurance"
    for p in catalogue.products():
        assert (docs / f"{p['id']}.md").exists(), p["id"]


def test_product_names_are_found_in_text():
    assert catalogue.find_in_text("compare the Lotus plan with Neem please") == ["health-lotus-care", "health-neem-essential"]
    assert catalogue.find_in_text("which plan is cheapest") == []


def test_catalogue_is_marked_sample():
    assert catalogue.is_sample() and all("(SAMPLE)" in p["name"] for p in catalogue.products())


def test_goal_cannot_be_overwritten_once_set():
    from advisory.extract import _candidates, apply
    p = profile(**HEALTH)
    assert "goal" not in [s.name for s in _candidates(p)]
    apply(p, {"goal": "term"})
    assert p.get("goal") == "health"


def test_trace_can_withhold_personal_text():
    from trust.audit import Trace
    trace = Trace("s")
    trace.add("stt", language="en-IN", transcript="I earn 12 lakh and live in Bangalore")
    trace.withhold("stt", "transcript")
    assert "12 lakh" not in str(trace.steps) and "Bangalore" not in str(trace.steps)
    assert trace.steps[0]["language"] == "en-IN"


def test_facts_say_how_many_plans_matched():
    rec = recommend(profile(**{**HEALTH, "maternity_needed": True}), consent_ok=True)
    assert rec.facts["rec:matched"] == "1 of the 3 plans in the catalogue matched on age and maternity cover."
    assert "rec:matched" in recommend(profile(**TERM), consent_ok=True).facts


def test_extraction_ignores_fields_backed_by_throwaway_words(monkeypatch):
    import asyncio, json
    from advisory import extract as ex
    flood = {k: {"value": v, "evidence": "no"} for k, v in
             {"city_tier": "metro", "members": "family", "existing_health_source": "none"}.items()}
    flood["existing_health_source"] = {"value": "none", "evidence": "do not have any"}

    async def fake_chat(messages, **kwargs):
        return json.dumps(flood)
    monkeypatch.setattr(ex, "chat", fake_chat)
    p = profile(**{**HEALTH, "existing_health_source": "employer"})
    got = asyncio.run(ex.extract("no, we do not have any", p, "existing_health_source"))
    assert got == {"existing_health_source": "none"}   # the asked field is kept; the volunteered ones are not


def test_person_who_cannot_answer_is_offered_a_human(monkeypatch):
    import asyncio
    from advisory import flow as flowmod
    from trust.audit import Trace

    async def nothing(text, prof, asking):
        return {}

    async def say(instruction, language):
        return "a question"
    monkeypatch.setattr(flowmod.extract, "extract", nothing)
    monkeypatch.setattr(flowmod.extract, "phrase", say)

    async def scenario():
        flow, trace, turns = flowmod.AdviceFlow("s"), Trace("s"), []
        for _ in range(flowmod.MAX_MISSES):
            turns.append(await flow.handle("blah", "en-IN", "English", True, trace, force=True))
        return turns
    turns = asyncio.run(scenario())
    assert [t.handoff_after for t in turns] == [False, False, True]
    assert "connect you to a person" in turns[-1].text


@pytest.mark.parametrize("text, number", [("दो बच्चे", 2), ("तीन लोग", 3), ("मेरे पांच बच्चे", 5), ("बारह", 12), ("three people", 3)])
def test_hindi_and_english_number_words(text, number):
    from advisory.profile import parse_int
    assert parse_int(text) == number


def test_number_words_need_word_boundaries():
    from advisory.profile import parse_int
    for text in ("someone", "tension", "none of them", "दोस्त", "एकदम"):
        assert parse_int(text) is None, text


def test_hindi_money_words():
    assert parse_money("बारह लाख") == 12 * LAKH and parse_money("बीस लाख रुपये") == 20 * LAKH


@pytest.mark.parametrize("text, count", [("me, my wife and our 2 kids", 2), ("मैं, मेरी पत्नी और हमारे दो बच्चे", 2),
                                         ("I am 34 and have three children", 3), ("we have no kids", None), ("just me", None)])
def test_children_count_is_read_in_code(text, count):
    from advisory.profile import children_in
    assert children_in(text) == count


def test_progress_clears_the_count_of_misses(monkeypatch):
    """Two earlier misses, then good answers, then one more miss: that is one miss, not three."""
    import asyncio
    from advisory import flow as flowmod
    from trust.audit import Trace
    answers = iter([{}, {}, {"goal": "health"}, {"age": 34}, {}])

    async def scripted(text, prof, asking):
        return next(answers)

    async def say(instruction, language):
        return "a question"
    monkeypatch.setattr(flowmod.extract, "extract", scripted)
    monkeypatch.setattr(flowmod.extract, "phrase", say)

    async def scenario():
        flow, trace = flowmod.AdviceFlow("s"), Trace("s")
        turns = [await flow.handle("a", "en-IN", "English", True, trace, force=True),
                 await flow.handle("b", "en-IN", "English", True, trace, force=True),
                 await flow.handle("c", "en-IN", "English", True, trace),            # an answer, found on the first look
                 await flow.handle("d", "en-IN", "English", True, trace),            # another
                 await flow.handle("e", "en-IN", "English", True, trace, force=True)]  # one miss
        return turns
    turns = asyncio.run(scenario())
    assert not any(t.handoff_after for t in turns)
