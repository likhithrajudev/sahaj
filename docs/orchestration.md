# The orchestrator: intents, graph, caching and the workflow report

## What changed and why

Before, a one-word router prompt decided what a message meant and a chain of `if`s in the session acted on it. The prompt had drifted (two contradictory `loan` entries, one promising EMI calculations and bank-rate comparisons that nothing could answer), gave no confidence, and had no examples.

Now:

1. A **classifier** (`orchestrator/intent.py`, prompt in `orchestrator/prompts.py`) returns a structured decision: one of ten intents, a confidence, a detail level (brief or deep) and a short reason.
2. A **LangGraph graph** (`orchestrator/graph.py`) turns the decision into a reply through explicit nodes, each timed and recorded.
3. A **LangChain chat model** (`services/llm.py`) is the single path to Sarvam, with retries, caching hooks and per-call telemetry.
4. **Caching** at four levels (below), none of which stores anything personal.
5. A **workflow report** built from the audit trail (`report/`, `GET /audit/report/...`).

## Intents

| Intent | Handled by | Notes |
|---|---|---|
| `insurance_explain` | insurance RAG | What a policy term, premium, waiting period, exclusion or claim means; term vs whole life |
| `insurance_advice` | needs-analysis flow | Recommendation, how much cover; also any answer to the advisor's question |
| `insurance_compare` | comparison | Named plans, or the plans of one kind |
| `loan_explain` | loan RAG (lender's KFS + general) | What the user's own offer says |
| `loan_calculator` | calculator | EMI and interest saved by prepaying: **computed by code** (`loan/calc.py`), never by the model |
| `loan_guidance` | loan RAG (general explanations only) | How loans work, kinds of loans, how to apply, paying less interest |
| `loan_rates_comparison` | decline | Rates across banks, which bank is cheapest, "will I be approved": Sahaj has no data, so it says so and offers a person |
| `human_handoff` | handoff | Asks for a person, complaint, anger. Never second-guessed, even at low confidence |
| `greeting` | front desk | Hello, thanks, "what can you do" |
| `out_of_scope` | decline | Anything else, including attempts to override the rules. Answered from fixed text, so a joke or an instruction in the message gets no compliance |

Below confidence 0.6 (`INTENT_MIN_CONFIDENCE`) the graph asks the user to clarify instead of guessing.

## The graph

```
START -> continue_active --(reply to an active conversation)--> guard -> END
              \--> classify -> clarify | insurance_rag | advice | compare | loan_rag | calculator | decline | greeting | handoff
                                  \--> guard -> END
```

`continue_active` gives an active needs analysis or loan calculation the first look at a message, because a reply mid-conversation is usually an answer to the question just asked. That saves a classifier call and keeps "34" from being classified in isolation. `guard` runs the guardrails and fact-checks on whatever reply was produced. WebSocket I/O stays in `Session`; the graph only decides. There is **no checkpointer on purpose**: a checkpoint would persist what the person told us.

`GET /audit/report/{session}` includes the graph as a Mermaid diagram.

## How well the classifier decides

`python tests/eval_intents.py` (live model; add `--held-out` and a run count):

| Set | Result |
|---|---|
| Main set, 81 messages, ten intents, English/Hindi/Hinglish/Tamil | 100% |
| **Held-out set**, 47 messages written without reference to the prompt's examples | **97.9%** (one arguable miss: a Hindi "how much instalment will I pay?" read as a calculation) |
| Ambiguous messages kept below the confidence threshold | 5 of 5 |
| Mean confidence when right / when wrong | 0.95 / 0.85 |

The main set overlaps the prompt's examples, so quote the held-out figure. Both sets are small: re-measure with real conversations.

## Prompt caching: what works and what was measured

Sarvam reports `cached_tokens` per call (and honours an `x-session-affinity` header). Measured on this model:

- **Static prompt first is what matters.** The classifier prompt is one fixed text of ~1,700 tokens with everything variable in the user message. Its input is **95-97% served from Sarvam's cache**. Generation prompts are built static-first too (`agents/base.system_prompt`), but are short and their documents vary, so only about 20% is cached. The fact-check prompts are under Sarvam's size threshold (roughly 1,000 tokens) and are about 3% cached. A test (`tests/test_orchestrator.py`) guards the static-first layout.
- **The affinity header has little effect on a prompt that is already warm.** With the header off, the classifier was still 96-97% cached. On a brand-new long prefix, hits appeared only with the header. It is cheap and documented, so it is sent (one key per conversation; `SARVAM_AFFINITY=false` turns it off), but do not expect much from it on the classifier.
- **Latency barely moves with provider caching** (about 340-410 ms per classifier call either way). The benefit is cost: cached tokens are billed lower on Sarvam's pricing pages. Set `PRICE_INPUT_PER_M`, `PRICE_OUTPUT_PER_M` and `PRICE_CACHED_PER_M` to have the report estimate it.

App-level caches (in memory, per process, never written to disk, expire after `CACHE_TTL_SECONDS`):

| Cache | Holds | Measured effect |
|---|---|---|
| Verified answers | A reply that already passed every guardrail, keyed by question, previous question, language, depth and the **hash of each clause used** | A repeated question went from **1.0-2.0 s and 4 model calls to 5-9 ms and none**. Editing a document changes the hashes, so stale answers are never served |
| Classifier | The intent of a non-personal message | Skips a model call for repeats |
| Embeddings | Query vectors | Skips local embedding work for repeats |

**Privacy rules for every cache:** nothing is cached while a needs analysis or loan calculation is active, when the text contains a digit or a masked identifier (amounts, ages, PAN, phone), or when a reply was blocked. Greetings and declined requests do not count as the "previous question" that a follow-up depends on. `APP_CACHE_ENABLED=false` turns all app caches off.

## The workflow report

`GET /audit/report/{session}?format=json|md|html&include_text=true|false` (admin key). `GET /audit/report?limit=50` gives the same measures across recent sessions. `GET /audit/caches` shows live cache hit rates.

It contains: overview, intent mix and confidence, routing paths with the graph diagram, latency per node (mean, p50, p95), model usage per purpose with input, output and provider-cached tokens, app-cache hit rates, guardrail results and fallback rate, retrieval quality, consents, recommendations (ranges only), and a turn-by-turn table. `docs/sample-workflow-report.md` is a real example.

It is built only from the audit trail, which already holds no personal answers (those turns are recorded as withheld), so the report cannot show them either. `include_text=false` removes the remaining transcripts and replies, leaving metrics only. Not measured: speech recognition and speech synthesis time.

## Running it

Python 3.12 is required (LangGraph 1.x and LangChain 1.x need 3.10 and 3.11+). Create the environment with `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

## Known limits

- The intent set is fixed in two places (`orchestrator/intent.py` and the prompt); add an intent to both, to `graph.ROUTES`, and to the evaluation set.
- Loan answers come from one sample KFS and a general concepts document. Real lender documents are needed for real answers.
- The calculators use the reducing-balance method; a lender's own figure can differ slightly, which the answer says.
- Hindi number words are understood only up to the round tens; speech recognition usually writes digits.
