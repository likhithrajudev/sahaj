# Compliance map (working document, not legal advice)

Maps what Sahaj does to the regulatory expectations it must meet. **Every row needs review by compliance or legal before it is used as evidence.** "Source" means where the expectation came from. Items marked *summary* come from law-firm summaries of the RBI Digital Lending Directions, 2025, not from reading the Directions themselves, so check them against the RBI text.

| Expectation | Source | Control in Sahaj | Status |
|---|---|---|---|
| Explicit, auditable borrower consent | RBI Digital Lending Directions 2025 (*summary*) | Consent ledger: purpose-bound, versioned, SHA-256 of the exact text shown, channel, expiry. Hash-chained, append-only. Nothing is processed without `conversation` consent. | Built. **Consent texts are drafts.** |
| Consent can be withdrawn | same (*summary*) | `consent` message with `granted:false`. Recorded as a new ledger entry; in-memory history and PII vault are wiped. | Built for `conversation`. Downstream revocation (data already shared with lenders or insurers) not built. |
| Data collected only as needed; deletion on request | same (*summary*) | PII is masked before the LLM, the logs and the audit trail, so the ledger holds no raw identifiers. | Masking built. **Deletion-request flow not built.** |
| Key Facts Statement shown to the borrower | same (*summary*) | The loan agent answers only from the lender's KFS clauses and cites them. | **KFS display and acceptance step not built.** Needs the real lender KFS. |
| Regulated entity is responsible for its LSP's conduct | same (*summary*) | Full per-turn trace (`/audit`), human handoff, no-advice guardrail. | Built. Lender agreements and monitoring are outside the code. |
| LSPs must not act as salesmen | same (*summary*) | Agents explain documents and never recommend or rank products. Pattern check for advice phrasing (English and Hindi) plus a prompt rule. | Built, with known gaps: other languages rely on the prompt and the fact-checker. |
| Funds flow directly between lender and borrower | same (*summary*) | Payments are not built. Razorpay settlement must be set up per lender. | **Not built.** |
| No invented terms | Product requirement | Answers only from clauses retrieved from the knowledge base (pgvector, cosine similarity); every statement cited; numbers must appear in the cited clause; an LLM fact-check blocks added conditions, implications and off-point answers. Failures are replaced with "I can't confirm that" and, twice in a row, a human handoff. | Built. Fail-closed, so some correct answers are blocked. Model-based checks are not guaranteed. |
| Traceable source of every answer | Product requirement | Each turn's trace records the retrieved clauses with their cosine similarity and the SHA-256 of the clause text, so you can prove which wording an answer was based on. | Built. Document version control and approval workflow (who approved this wording, when) is not built. |
| Recommending policies only after understanding the person | Product requirement | A needs analysis the code enforces: required fields, a read-back the person must confirm, and a gate (`engine.recommend`) that refuses without consent, completeness and confirmation. Unit-tested. | Built. |
| Suitability of a recommendation can be reproduced and explained | Product requirement | The ranking is deterministic and versioned. The `recommendation` ledger entry holds the rules version, catalogue hash, banded profile and per-plan score breakdown. The person sees the same breakdown on the card. | Built. **Sizing rules and weights are development defaults needing actuarial and compliance approval** (`docs/advisory.md`). |
| Disclosures with every recommendation | Product requirement | Fixed, versioned text (English and Hindi) shown on the card and the first two spoken. | Built as drafts. **Compliance must supply the wording, how Sahaj is paid, its registration details and approved translations.** |
| Personal details used for advice only with consent, and minimised | DPDP principles (*not researched*) | Separate `needs_analysis` consent, withdrawable (it wipes the analysis). Answers are kept out of traces and hand-off history; audit holds ranges only. | Built. DPDP rules themselves are **not mapped**. |
| No pressure or misleading claims | Product requirement | Recommending wording is allowed only for text built from the engine's facts; directive or pressure phrasing ("you must buy", "guaranteed", "limited time") is always blocked. | Built for English and Hindi phrasing; other languages rely on the model checks. |
| Advice can be switched off | Product requirement | `ADVISORY_ENABLED=false` makes Sahaj explain and compare only. | Built. |
| One-tap human handoff | Product requirement | Button message plus automatic triggers. A masked packet (recent messages, active consents, trace id) is recorded and POSTed to `HANDOFF_WEBHOOK_URL`. | Built. **The live human console is not built.** |
| Full audit trail | Product requirement | Every turn records the masked transcript, route, answer, guardrail verdict and ids. `/audit/verify` detects tampering. | Built on SQLite. Move to Postgres and anchor the head hash outside the database. |
| IRDAI requirements (solicitation, disclosures, policyholder protection, grievance, record keeping) | **Not yet mapped** | To be derived from IRDAI's regulations for the registration category Sahaj applies for. | **Open.** Needs the registration category decision first. |
| DPDP Act (consent, purpose limitation, consent managers) | **Not researched** | Consent is already purpose-bound and revocable. | **Open.** |
| Video KYC | Chosen route | `video_kyc` consent purpose is defined. No vendor integrated. | **Not built.** Pick a vendor first. |

## Known technical limits

- PII masking is pattern-based. It covers PAN, Aadhaar-shaped numbers, phone numbers, emails, UPI IDs and account-like numbers, including spelled-out and non-English digits. It does not catch names, addresses, dates of birth, or identifiers spoken as words ("nine eight seven…"), nor letters spoken in Indian scripts.
- Guardrails are checked on text after the model has written it. The advice patterns cover English and Hindi phrasing only.
- The model-based fact-check has been tested on a small sample (12 cases) plus repeated runs of 16 question types against the sample documents (about 4 runs each; no wrong answer was shown, some correct ones were blocked). Measure it on real documents before relying on it. Results varied between runs because the chat model is not deterministic.
- Retrieval uses cosine similarity over `multilingual-e5-large` embeddings. On the sample documents it found the right clause in the top 3 for 20 of 20 test questions (19 of 20 at rank 1) across English, Hindi, Tamil, Telugu, Bengali, Marathi and Hinglish. The documents are tiny, so this says little about real policy wording: re-run `tests/eval_retrieval.py` with real documents and questions. Similarity scores are compressed (relevant about 0.77 to 0.90, unrelated about 0.70), so the cutoff (0.75) removes only clearly unrelated text. Whether the answer exists is decided by the answer checks, not by retrieval.
- Clauses longer than about 1,800 characters are truncated by the embedding model. Split long clauses in the source documents.
- Documents in `knowledge/` are **synthetic samples**. Replace them with insurer- and lender-approved documents before any real use.
- Users are not authenticated yet, so consent belongs to an anonymous session.

## Advisory-specific limits

- The product catalogue is **fictional sample data**. No real insurer, plan, premium or claim ratio is represented, and "claim settlement ratio" figures in it are invented.
- A model-written recommendation summary is checked by code and by two narrow model questions. In testing (32 of 32 summaries across English and Hindi and four plan types) all passed, but that is a small sample and results vary between runs. A failed summary is replaced by fixed text; the structured card is always shown.
- Plan comparisons and recommendations do not use real underwriting. Premiums are indicative table lookups.
- Brand-name matching can fail when speech recognition mishears a plan name.
- IRDAI's rules on who may advise, required disclosures, need-based selling, record keeping and complaints are **not yet mapped**. Do not describe this feature as compliant with them until that is done with your registration category in hand.

## Orchestrator, caching and reporting

- **Intent classification** decides which specialist handles a message. It is measured (97.9% on a held-out set of 47 messages) but it is a model: a wrong intent leads to a wrong handler, and every handler's reply still passes the guardrails. Anything unclear (confidence under 0.6) is clarified, not guessed, and a request for a person always reaches one.
- **What Sahaj will not do is said from fixed text**, not generated: rate comparison across banks, approval predictions, anything outside insurance and loans. This is deliberate so an instruction inside a message cannot make it comply.
- **Caching holds nothing personal.** App caches are in process memory only, never persisted, expire after an hour, are skipped while a needs analysis or loan calculation is active and for any text containing digits or masked identifiers, and cached answers are invalidated when a source clause changes. Sarvam's own prompt cache sees prompts the model receives; prompts for personal-details turns contain what the person said, so confirm with Sarvam how long its cache retains prompt content and whether that fits your data-processing terms. **This is not verified here.**
- **The workflow report** is built from the audit trail and so holds no personal answers. It does include transcripts and replies of non-personal turns unless `include_text=false`; treat it as back-office data behind the admin key.
- Loan calculators use the reducing-balance method and say that a lender's figure can differ. They are not a Key Facts Statement and must not be presented as one.
