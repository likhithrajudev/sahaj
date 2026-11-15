# Insurance advice: how it works and what must be approved

Sahaj can explain term and whole-life insurance, compare health plans, explain premiums, exclusions, waiting periods and claims, size cover from age, income, dependents and existing cover, and recommend specific plans. Because recommending is advice, it is built so that **a person's requirements are fully understood first, and a recommendation is decided by code you can audit, not by the language model.**

## Who decides what

| Step | Done by | Why |
|---|---|---|
| Reading a number or choice out of what the person said | Model, then **re-checked in code** | Quoted evidence must appear in what they said and amounts must re-parse to the same figure, so "12 lakh" cannot become 12 crore. Yes/no and list answers are accepted only for the question just asked. |
| Which question comes next, and when we know enough | Code (`advisory/profile.py`) | Fixed required fields per goal. The optional "what matters most" question is still always asked. |
| Whether a recommendation may be made | Code (`engine.recommend`) | Refuses unless: advice is enabled, `needs_analysis` consent is active, the profile is complete, and the person confirmed it. Any change un-confirms it. Tested. |
| Cover size, eligibility, premium, ranking | Code (`advisory/engine.py`, `rules.py`) | Deterministic and versioned: the same inputs always give the same answer. |
| Putting the result into words, in the person's language | Model | Every figure it says must appear in the engine's facts, and a separate model check rejects claims the facts do not make. If checks fail three times, fixed text is used and the card still shows everything. |
| Disclosures | Fixed text (`advisory/disclosures.py`) | Never written by the model. |

## What a recommendation contains

Up to three ranked plans, never a single "best". Each shows its premium, highlights, why it ranks where it does (only criteria where it is strictly best among those compared), and a score breakdown per criterion. A stated priority (lowest price, claim reliability, shorter waiting periods, riders) raises the weight of its criterion. A need for maternity cover filters out plans without it, and the answer says how many of the catalogue's plans matched.

## What is recorded

The ledger gets a `recommendation` entry with the rules version, the catalogue's hash, the **banded** profile (age range, income range, dependents, cover ranges, never exact figures), the per-plan score breakdown, the disclosure version and the language. What the person says in answer to the questions is **not** recorded in the trace or in the conversation history that human-handoff packets use. Field *names* extracted per turn are recorded, never values.

## Things that need approval before real use

1. **Sizing rules and ranking weights** (`advisory/rules.py`): income multiples, retirement age, health cover by city and family, weights. They are development defaults and rules of thumb, not IRDAI formulas, and are not actuarially validated. Change them together with `RULES_VERSION`.
2. **Consent text** (`needs_analysis` in `trust/consent.py`) and **disclosures**, including how Sahaj is paid and its IRDAI registration details, which are not yet included. Translations beyond English and Hindi.
3. **IRDAI requirements for advice** have not been mapped (see `compliance.md`).

## Replacing the sample catalogue

`catalogue/sample-catalogue.json` and the wording documents `knowledge/insurance/<plan-id>.md` are **fictional** (every name carries "(SAMPLE)"). They are generated from one source so figures agree. To use real plans:

1. Load real plan data in the same shape (see the existing entries: `goal` of `term`, `whole_life` or `health`; age limits; premium tables or rates by age band; the facts the ranking and comparison use). A different source of data only needs to produce the same dictionaries; `advisory/catalogue.py` is the one place that reads them.
2. Put each insurer-approved policy wording in `knowledge/insurance/<plan-id>.md`, one `## <clause> <title>` section per clause, with the file name equal to the plan's `id`, then run `python -m rag.ingest`.
3. Keep the general explanations in `concepts-*.md` reviewed by compliance.

Premiums here are looked up in tables per age band and sum insured, with no interpolation: a plan with no entry for the person is not offered. Real insurers price on more factors, so a live pricing API will be needed for real quotes.

## Known limits

- Plan-name matching is by brand word, so speech recognition mishearing a name ("Peepal" heard as "people") makes Sahaj compare the whole plan type instead.
- Only English and Hindi number words are parsed ("twelve lakh", "बारह लाख"), and Hindi only up to the round tens. Speech recognition usually writes digits.
- The read-back may be shorter than the details when spoken; the `profile_summary` card is complete.
- Parents are not priced separately: for health, "age" is the eldest person covered.
- Several model calls per advice turn (extract, phrase, narrate, two checks) add latency: expect a few seconds per turn.
