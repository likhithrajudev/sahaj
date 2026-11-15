"""Sizing and ranking rules for recommendations.

Every number here is a DEVELOPMENT DEFAULT and a rule of thumb, not an IRDAI formula and not actuarially
validated. They need approval from your actuarial and compliance people before real use. Change the values
and RULES_VERSION together: each recommendation records the version so it can be reproduced later.
"""
LAKH = 100_000
CRORE = 10_000_000

RULES_VERSION = "2026-11-draft-1"
TOP_N = 3  # plans shown; never a single "best"

# ---- life cover (term and whole life): need = income x multiple + loans - existing life cover
RETIREMENT_AGE = 60       # the multiple is capped at the working years left
MIN_TERM_YEARS = 10
LIFE_MULTIPLE_BY_DEPENDENTS = [(0, 5), (2, 10), (99, 12)]  # (up to this many dependents, income multiple)

# ---- health cover: base sum insured by city, scaled by who is covered
HEALTH_BASE_SI = {"metro": 10 * LAKH, "non_metro": 5 * LAKH}
HEALTH_MEMBERS_FACTOR = {"self": 1.0, "self_spouse": 1.5, "family": 2.0}
EMPLOYER_COVER_COUNTS = False  # employer cover can end when the job does, so it is not subtracted from the need

AFFORDABILITY_WARN = 0.10  # warn when the top plan's yearly premium exceeds this share of yearly income

# ---- ranking: weights per criterion (sum to 1). A stated priority adds PRIORITY_BOOST to its criterion.
WEIGHTS = {
    "term": {"premium": 0.45, "claim_ratio": 0.25, "features": 0.30},
    "whole_life": {"premium": 0.55, "claim_ratio": 0.30, "paying_term": 0.15},
    "health": {"premium": 0.30, "ped_waiting": 0.20, "cost_sharing": 0.15, "claim_ratio": 0.15,
               "restoration_bonus": 0.10, "network": 0.10},
}
PRIORITY_BOOST = 0.25
PRIORITY_TO_CRITERION = {
    "low_premium": "premium",
    "claim_reliability": "claim_ratio",
    "low_waiting": "ped_waiting",
    "pre_existing_cover": "ped_waiting",
    "riders": "features",
}
ROOM_RENT_PENALTY = [("no limit", 0), ("single private", 5), ("limited to", 10)]  # extra cost-sharing points
