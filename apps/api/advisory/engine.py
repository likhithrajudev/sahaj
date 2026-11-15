"""The recommendation engine. Pure and deterministic: the same profile always gives the same answer, and no
language model is involved. The model only puts these results into words afterwards."""
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
from advisory import catalogue, rules
from advisory.catalogue import money
from advisory.profile import LIFE, Profile
from advisory.rules import CRORE, LAKH


class AdvisoryRefused(Exception):
    """Raised instead of recommending. `reason` is one of: disabled, no_consent, incomplete, unconfirmed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Recommendation:
    goal: str
    cover: dict                                   # suggested cover and the basis it was worked out from
    items: List[dict] = field(default_factory=list)
    facts: Dict[str, str] = field(default_factory=dict)   # what the model may say, keyed for citation
    audit: dict = field(default_factory=dict)


# ------------------------------------------------------------------ the gate
def recommend(profile: Profile, *, consent_ok: bool) -> Recommendation:
    """Recommend plans. Refuses unless the person has consented and the profile is complete and confirmed."""
    if not config.ADVISORY_ENABLED:
        raise AdvisoryRefused("disabled")
    if not consent_ok:
        raise AdvisoryRefused("no_consent")
    if not profile.complete():
        raise AdvisoryRefused("incomplete")
    if not profile.confirmed:
        raise AdvisoryRefused("unconfirmed")
    return _recommend(profile)


# ------------------------------------------------------------------ cover sizing
def _round_up(n: float, step: int) -> int:
    return int(math.ceil(n / step) * step)


def life_cover(profile: Profile) -> dict:
    age, income = profile.get("age"), profile.get("annual_income")
    dependents = profile.get("dependents")
    multiple = next(m for limit, m in rules.LIFE_MULTIPLE_BY_DEPENDENTS if dependents <= limit)
    working_years = max(rules.RETIREMENT_AGE - age, 0)
    multiple = min(multiple, working_years)
    gross = income * multiple + profile.get("liabilities")
    need = max(gross - profile.get("existing_life_cover"), 0)
    return {
        "kind": "life", "need": _round_up(need, 5 * LAKH) if need else 0, "multiple": multiple,
        "basis": (f"yearly income {money(income)} x {multiple} (capped at the {working_years} working years left "
                  f"to age {rules.RETIREMENT_AGE}), plus loans {money(profile.get('liabilities'))}, "
                  f"less existing cover {money(profile.get('existing_life_cover'))}"),
    }


def health_cover(profile: Profile) -> dict:
    base = rules.HEALTH_BASE_SI[profile.get("city_tier")]
    factor = rules.HEALTH_MEMBERS_FACTOR[profile.get("members")]
    need = base * factor
    source = profile.get("existing_health_source")
    existing = profile.get("existing_health_cover", 0) if source == "personal" else 0
    note = None
    if source == "employer":
        note = ("Health cover from an employer may end if the job changes, so it was not subtracted from the "
                "suggested cover." if not rules.EMPLOYER_COVER_COUNTS else None)
    need = max(need - existing, 0)
    return {
        "kind": "health", "need": int(need), "note": note,
        "basis": (f"base cover {money(base)} for a {profile.get('city_tier').replace('_', '-')} city, scaled by "
                  f"{factor:g} for {profile.get('members').replace('_', ' and ')}, less existing own cover {money(existing)}"),
    }


# ------------------------------------------------------------------ premiums and eligibility
def _band_index(product: dict, age: int) -> Optional[int]:
    return next((i for i, (lo, hi) in enumerate(product["age_bands"]) if lo <= age <= hi), None)


def _r10(x: float) -> int:
    return int(round(x / 10.0) * 10)


def _offer(product: dict, profile: Profile, need: int) -> Optional[dict]:
    """The product priced for this person, or None if they are not eligible or no price exists."""
    age = profile.get("age")
    if not product["age_min"] <= age <= product["age_max"]:
        return None
    band = _band_index(product, age)
    if band is None:
        return None
    goal = product["goal"]

    if goal == "term":
        cover = min(max(_round_up(need, product["cover_step"]), product["cover_min"]), product["cover_max"])
        rate = product["rate_per_crore"]["smoker" if profile.get("smoker") else "non_smoker"][band]
        years = min(max(rules.RETIREMENT_AGE - age, rules.MIN_TERM_YEARS), product["max_maturity_age"] - age)
        return {"cover": cover, "premium": _r10(rate * cover / CRORE), "term_years": years}

    if goal == "whole_life":
        cover = min(max(_round_up(need, product["cover_step"]), product["cover_min"]), product["cover_max"])
        return {"cover": cover, "premium": _r10(product["rate_per_10_lakh"][band] * cover / (10 * LAKH))}

    # health: smallest offered sum insured that meets the need, else the largest on offer
    if profile.get("maternity_needed") and not product["maternity"]:
        return None
    options = sorted(product["si_options"])
    si = next((s for s in options if s >= need), options[-1])
    lo, hi = product["age_bands"][band]
    base = product["premium_by_band"].get(f"{lo}-{hi}", {}).get(str(si))
    if base is None:
        return None
    factor = product["floater_factor"][str(profile.members_count())]
    return {"cover": si, "premium": _r10(base * factor), "meets_need": si >= need}


def quote(product: dict, profile: Profile) -> Optional[dict]:
    """Indicative price of one plan for a complete profile (None if the person is not eligible or not priced)."""
    if not profile.complete():
        return None
    if product["goal"] != profile.get("goal"):
        return None
    sizing = life_cover(profile) if product["goal"] in LIFE else health_cover(profile)
    return _offer(product, profile, sizing["need"]) if sizing["need"] else None


# ------------------------------------------------------------------ ranking
def _raw(product: dict, offer: dict) -> Dict[str, float]:
    """Raw criterion values. `HIGHER`/`LOWER` below say which direction is better."""
    goal = product["goal"]
    per_unit = offer["premium"] / offer["cover"]  # yearly premium per rupee of cover
    if goal == "term":
        return {"premium": per_unit, "claim_ratio": product["claim_settlement_ratio"],
                "features": product["riders_included"]}
    if goal == "whole_life":
        return {"premium": per_unit, "claim_ratio": product["claim_settlement_ratio"],
                "paying_term": product["premium_paying_term_years"]}
    penalty = next((p for key, p in rules.ROOM_RENT_PENALTY if key in product["room_rent"]), 10)
    bonus_cap = int(re.findall(r"\d+", product["no_claim_bonus"])[-1])
    return {"premium": per_unit, "ped_waiting": product["ped_waiting_months"],
            "cost_sharing": product["copay_percent"] + penalty, "claim_ratio": product["claim_settlement_ratio"],
            "restoration_bonus": (1 if product["restoration"] else 0) + bonus_cap / 100,
            "network": product["network_hospitals"]}


LOWER_IS_BETTER = {"premium", "ped_waiting", "cost_sharing", "paying_term"}
LABELS = {"premium": "premium for the cover", "claim_ratio": "claim settlement ratio", "features": "riders included",
          "paying_term": "premium paying term", "ped_waiting": "waiting period for pre-existing diseases",
          "cost_sharing": "co-payment and room rent limits", "restoration_bonus": "restoration and no-claim bonus",
          "network": "network hospitals"}


def _weights(goal: str, priorities: List[str]) -> Dict[str, float]:
    weights = dict(rules.WEIGHTS[goal])
    for priority in priorities:
        criterion = rules.PRIORITY_TO_CRITERION.get(priority)
        if criterion in weights:
            weights[criterion] += rules.PRIORITY_BOOST
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _rank(goal: str, offers: List[dict], priorities: List[str]) -> List[dict]:
    raws = [_raw(o["product"], o) for o in offers]
    weights = _weights(goal, priorities)
    for offer, raw in zip(offers, raws):
        breakdown = {}
        for criterion, weight in weights.items():
            values = [r[criterion] for r in raws]
            lo, hi = min(values), max(values)
            norm = 1.0 if hi == lo else (hi - raw[criterion]) / (hi - lo) if criterion in LOWER_IS_BETTER \
                else (raw[criterion] - lo) / (hi - lo)
            breakdown[criterion] = {"value": raw[criterion], "score": round(norm, 4), "weight": round(weight, 4),
                                    "contribution": round(norm * weight, 4)}
        offer["breakdown"] = breakdown
        offer["score"] = round(sum(b["contribution"] for b in breakdown.values()), 4)
    # ties broken by product id so the order is reproducible
    return sorted(offers, key=lambda o: (-o["score"], o["product"]["id"]))


def _reasons(ranked: List[dict]) -> None:
    """For each plan, name the criteria where it is strictly the best, using catalogue values."""
    for offer in ranked:
        reasons = []
        for criterion, b in offer["breakdown"].items():
            others = [o["breakdown"][criterion]["score"] for o in ranked if o is not offer]
            if others and b["score"] == 1.0 and max(others) < 1.0:
                reasons.append(f"best on {LABELS[criterion]} among the plans compared")
        offer["reasons"] = reasons


# ------------------------------------------------------------------ assembling the result
def _highlights(product: dict, offer: dict) -> List[str]:
    goal = product["goal"]
    if goal == "term":
        return [f"claim settlement ratio {product['claim_settlement_ratio']} percent (sample data)",
                f"cover runs for {offer['term_years']} years", product["rider_text"]]
    if goal == "whole_life":
        return [f"claim settlement ratio {product['claim_settlement_ratio']} percent (sample data)",
                f"premiums are paid for {product['premium_paying_term_years']} years, cover lasts to age {product['coverage_till_age']}",
                f"it is {product['kind']}"]
    mat = product["maternity"]
    return [f"pre-existing diseases are covered after {product['ped_waiting_months']} months",
            f"co-payment {product['copay_percent']} percent" if product["copay_percent"] else "no co-payment",
            f"room rent: {product['room_rent']}",
            (f"maternity covered up to {money(mat['limit'])} after {mat['waiting_months']} months" if mat else "no maternity cover"),
            f"claim settlement ratio {product['claim_settlement_ratio']} percent (sample data)",
            f"{product['network_hospitals']} network hospitals"]


def _recommend(profile: Profile) -> Recommendation:
    goal = profile.get("goal")
    sizing = life_cover(profile) if goal in LIFE else health_cover(profile)
    rec = Recommendation(goal=goal, cover=sizing)
    income = profile.get("annual_income")

    if sizing["need"] == 0:
        rec.facts["rec:cover"] = (f"By the sizing rule used here, no additional cover is needed: {sizing['basis']}. "
                                  "Existing cover already meets or exceeds the estimated need.")
        rec.audit = _audit(profile, rec, [])
        return rec

    offers = []
    for product in catalogue.products(goal):
        offer = _offer(product, profile, sizing["need"])
        if offer:
            offers.append({"product": product, **offer})
    if not offers:
        rec.facts["rec:cover"] = (f"No plan in the catalogue matches this profile. Suggested cover "
                                  f"{money(sizing['need'])} ({sizing['basis']}).")
        rec.audit = _audit(profile, rec, [])
        return rec

    in_catalogue = len(catalogue.products(goal))
    ranked = _rank(goal, offers, profile.get("priorities", []))[:rules.TOP_N]
    _reasons(ranked)

    cover_word = "sum insured" if goal == "health" else "cover"
    rec.facts["rec:cover"] = f"Suggested {cover_word}: {money(sizing['need'])}. Worked out from {sizing['basis']}."
    if sizing.get("note"):
        rec.facts["rec:note"] = sizing["note"]
    for rank, offer in enumerate(ranked, start=1):
        p = offer["product"]
        sentence = (f"Rank {rank}: {p['name']} by {p['insurer']}. {cover_word.capitalize()} {money(offer['cover'])}, "
                    f"indicative yearly premium {money(offer['premium'])}. " + "; ".join(_highlights(p, offer)) + ".")
        if offer.get("meets_need") is False:
            sentence += f" This is the largest {cover_word} the plan offers, below the suggested {money(sizing['need'])}."
        if offer["reasons"]:
            sentence += " Why it ranks here: " + "; ".join(offer["reasons"]) + "."
        rec.facts[f"rec:{p['id']}"] = sentence
        rec.items.append({
            "rank": rank, "product_id": p["id"], "name": p["name"], "insurer": p["insurer"],
            "cover": offer["cover"], "annual_premium": offer["premium"], "highlights": _highlights(p, offer),
            "reasons": offer["reasons"], "score": offer["score"], "breakdown": offer["breakdown"],
            "meets_suggested_cover": offer.get("meets_need", True),
        })

    share = ranked[0]["premium"] / income
    rec.facts["rec:affordability"] = (f"The top-ranked plan's yearly premium is about {share * 100:.1f} percent of the "
                                      "stated yearly income." + (" That is above the level this advisor flags as a "
                                                                 "stretch for most budgets." if share > rules.AFFORDABILITY_WARN else ""))
    weights = _weights(goal, profile.get("priorities", []))
    rec.facts["rec:matched"] = (
        f"{len(offers)} of the {in_catalogue} plans in the catalogue matched on age"
        + (" and maternity cover" if profile.get("maternity_needed") else "") + ".")
    rec.facts["rec:screen"] = "The full details of every ranked plan are shown on the screen."
    rec.facts["rec:method"] = ("Plans are ranked using only: " + ", ".join(LABELS[c] for c in weights) +
                               ". Eligibility depends on age, cover range" +
                               (" and the need for maternity cover" if profile.get("maternity_needed") else "") + ".")
    rec.audit = _audit(profile, rec, rec.items)
    return rec


def _audit(profile: Profile, rec: Recommendation, items: List[dict]) -> dict:
    return {
        "rules_version": rules.RULES_VERSION, "catalogue_sha256": catalogue.version(),
        "catalogue_is_sample": catalogue.is_sample(), "profile_bands": profile.bands(),
        # Not the readable basis: it spells out the person's exact income and loans. The rule and its result are enough
        # to reproduce the figure together with the banded profile.
        "suggested_cover": {"rule": rec.cover["kind"], "multiple": rec.cover.get("multiple"), "need": rec.cover["need"]},
        "ranked": [{"product_id": i["product_id"], "rank": i["rank"], "annual_premium": i["annual_premium"],
                    "cover": i["cover"], "score": i["score"], "breakdown": i["breakdown"]} for i in items],
    }
