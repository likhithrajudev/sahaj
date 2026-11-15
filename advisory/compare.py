"""Side-by-side comparison of plans from the catalogue. The table is deterministic; the model only narrates it."""
from typing import Dict, List, Optional, Tuple

from advisory import catalogue, engine
from advisory.catalogue import money
from advisory.profile import Profile

CATEGORY_WORDS = [  # whole life first: "whole life" contains neither of the others, but order keeps it explicit
    ("whole_life", ("whole life", "whole-life", "होल लाइफ", "आजीवन")),
    ("term", ("term", "टर्म")),
    ("health", ("health", "mediclaim", "hospital", "स्वास्थ्य", "मेडिक्लेम", "अस्पताल")),
]


def category_in(text: str) -> Optional[str]:
    lowered = text.lower()
    return next((goal for goal, words in CATEGORY_WORDS if any(w in lowered for w in words)), None)


def rows(product: dict) -> List[Tuple[str, str]]:
    goal = product["goal"]
    csr = ("claim settlement ratio", f"{product['claim_settlement_ratio']} percent (sample data)")
    if goal == "term":
        return [("cover available", f"{money(product['cover_min'])} to {money(product['cover_max'])}"),
                ("cover can run up to age", str(product["max_maturity_age"])), ("riders", product["rider_text"]), csr,
                ("suicide exclusion", f"{product['suicide_exclusion_months']} months from the start date"),
                ("free-look period", f"{product['free_look_days']} days")]
    if goal == "whole_life":
        return [("cover available", f"{money(product['cover_min'])} to {money(product['cover_max'])}"),
                ("type", f"{product['kind']}: {product['kind_text']}"),
                ("premium paying term", f"{product['premium_paying_term_years']} years"),
                ("cover lasts to age", str(product["coverage_till_age"])),
                ("surrender allowed after", f"{product['surrender_after_years']} years"), csr]
    mat = product["maternity"]
    return [("sum insured options", ", ".join(money(s) for s in product["si_options"])),
            ("waiting period for pre-existing diseases", f"{product['ped_waiting_months']} months"),
            ("initial waiting period", f"{product['initial_waiting_days']} days"),
            ("waiting period for listed conditions", f"{product['specific_waiting_months']} months"),
            ("co-payment", f"{product['copay_percent']} percent of every claim" if product["copay_percent"] else "none"),
            ("room rent", product["room_rent"]),
            ("maternity", f"covered up to {money(mat['limit'])} after {mat['waiting_months']} months" if mat else "not covered"),
            ("restoration of sum insured", "yes, once a year" if product["restoration"] else "no"),
            ("no-claim bonus", product["no_claim_bonus"]), ("network hospitals", str(product["network_hospitals"])), csr]


def compare(text: str, profile: Optional[Profile]) -> Optional[dict]:
    """{'facts', 'card', 'ids'} for the plans named in `text`, or for every plan of the type named. None if unclear."""
    ids = catalogue.find_in_text(text)
    goals = {catalogue.by_id(i)["goal"] for i in ids}
    if len(goals) > 1:  # a brand with several kinds of plan ("Orchid"): the type decides, or we must ask
        goals = {category_in(text)} - {None}
    goal = next(iter(goals), None) or category_in(text)
    if goal is None:
        return None
    if len(ids) < 2:  # one plan named (or none): compare it with the other plans of its type
        ids = [p["id"] for p in catalogue.products(goal)]
    ids = [i for i in ids if catalogue.by_id(i)["goal"] == goal]

    facts: Dict[str, str] = {}
    plans = []
    for pid in ids:
        product = catalogue.by_id(pid)
        table = rows(product)
        offer = engine.quote(product, profile) if profile else None
        if offer:
            table.append(("indicative yearly premium for the suggested cover",
                          f"{money(offer['premium'])} for cover of {money(offer['cover'])}"))
        facts[f"{pid}:compare"] = f"{product['name']} by {product['insurer']}: " + "; ".join(f"{k}: {v}" for k, v in table) + "."
        plans.append({"id": pid, "name": product["name"], "insurer": product["insurer"], "rows": [list(r) for r in table]})
    card = {"type": "comparison", "goal": goal, "plans": plans, "sample_data": catalogue.is_sample(),
            "premiums_included": any(r[0].startswith("indicative") for p in plans for r in p["rows"])}
    return {"facts": facts, "card": card, "ids": ids}


def is_concept_question(text: str) -> bool:
    """'Difference between term and whole life' names two kinds of insurance, not plans: it is an explanation."""
    lowered = text.lower()
    return not catalogue.find_in_text(text) and any(w in lowered for w in CATEGORY_WORDS[0][1]) \
        and any(w in lowered for w in CATEGORY_WORDS[1][1])
