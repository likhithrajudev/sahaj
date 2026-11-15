# Sahaj Voice API: frontend integration guide

Talk to Sahaj by voice about insurance policies and loan offers. The client records the user's speech and sends it. The server replies with the transcript, a cited text answer and the answer as spoken audio. Sahaj routes each question to an insurance or loan specialist, and every turn passes consent, PII masking, answer-checking guardrails and an audit trail.

- **Voice endpoint:** `ws://127.0.0.1:8000/ws/voice` (use `wss://` in production)
- **Interactive REST docs:** `http://127.0.0.1:8000/docs`
- **Working reference client:** `apps/api/static/index.html`

## Session flow

```
connect    ← {"type":"session","id":"..."}
           ← {"type":"consent_required","purpose":"conversation","version":"...","text":"..."}
user taps "I agree" (show `text` verbatim, with accept and decline)
           → {"type":"consent","purpose":"conversation","granted":true}
           ← {"type":"consent","purpose":"conversation","status":"granted"}

per turn   → binary frame: one recording (max 30 seconds)
           ← {"type":"user","text":"..."}                 masked transcript
           ← {"type":"assistant","agent":"insurance","text":"... [doc:3.2]",
              "citations":[{"id":"doc:3.2","text":"..."}],"trace_id":"..."}
           ← binary frames: MP3 chunks of the spoken answer
           ← {"type":"done"}
```

The server remembers the last 20 messages for as long as the socket is open. **Closing the socket ends the session and resets the conversation.**

## Client → server

| Frame | Content |
|---|---|
| **Binary** | One complete recording (maximum 30 seconds). Send it only after `done`, `error` or `handoff`. |
| **Text (JSON)** | `{"type":"consent","purpose":"...","granted":true\|false}`: grant or withdraw consent. |
| | `{"type":"handoff"}`: the **talk to a human** button. Send it any time. |

## Server → client (JSON text frames)

| `type` | Fields | What to do |
|---|---|---|
| `session` | `id` | Keep it as the session reference for support requests. |
| `consent_required` | `purpose`, `version`, `text` | Show `text` exactly as sent with accept and decline buttons, then reply with a `consent` message. No audio is processed until `conversation` is granted. A second purpose, `needs_analysis`, is requested the first time the user asks for a recommendation: it covers using their age, income, family and existing cover. If they decline, Sahaj still explains and compares plans but will not ask for or use personal details. |
| `card` | `kind`, `card`, `trace_id` | Structured data to render as UI, sent just before the matching `assistant` message. See "Cards" below. Always trust the card over the spoken text for figures. |
| `consent` | `purpose`, `status` | Confirms `granted` or `revoked`. After `revoked` the server forgets the conversation. |
| `user` | `text` | The transcript as a user message. **Personal identifiers are already masked** (for example `[PAN_1]`, `[PHONE_1]`). Show it as is. |
| `assistant` | `agent`, `text`, `citations`, `trace_id` | The answer. `agent` is `insurance`, `loan`, `general` or `advice` (the needs analysis and recommendation). `text` contains source tags like `[policy:3.2]`. Render each tag as a link or footnote to the matching entry in `citations`, which holds the clause text. Keep `trace_id` for support. |
| *(binary)* | | MP3 chunks of the spoken answer. Join them in order. |
| `done` | none | The turn is finished. If you received no audio chunks, play nothing. Some languages are text only. |
| `handoff` | `reference`, `reason` | A human is taking over. Show the `reference` to the user and disable the talk button. The AI stops answering on this session. `reason` is `user_requested`, `guardrail_failures` (two answers in a row could not be verified) or `stuck_in_questions` (three turns of the needs analysis made no progress). If audio is sent after a handoff, the server repeats this event with `reference` only (no `reason`). |
| `error` | `message` | The turn failed (silence, bad audio, upstream failure). No `done` follows. The socket stays open, so let the user try again. |

### Cards

Render by `card.type`. The event's `kind` is the turn that produced it (`confirm`, `recommendation`, `compare`, `calc`). Typed in `packages/contracts`.

| `card.type` | When | Contents |
|---|---|---|
| `profile_summary` (`kind: confirm`) | The needs analysis is asking the user to confirm | `details`: the complete list of what Sahaj understood, as short lines. **Display it.** The spoken read-back can be shorter, and the user must see exactly what will be used before saying yes. |
| `recommendation` (`kind: recommendation`) | After the user confirms | `goal`, `suggested_cover` (`amount`, `basis`, `note` or null), `plans` (up to 3, ranked; each with `rank`, `product_id`, `name`, `insurer`, `cover`, `annual_premium`, `highlights`, `reasons`, `meets_suggested_cover`, `criteria` keyed by criterion with `value`, `score`, `weight`, `contribution`), `disclosures` (all of them, always show), `disclosures_version`, `sample_data`, `indicative_premiums`. |
| `comparison` (`kind: compare`) | The user asks to compare plans | `goal`, `sample_data`, `premiums_included`, `plans`, each with `id`, `name`, `insurer` and `rows` of `[label, value]` pairs: render as a table. |
| `loan_calculation` (`kind: calc`) | A loan calculation (EMI, or interest saved by prepaying) | `card.kind` (`emi` or `prepayment`), `inputs` (`principal`, `annual_rate_percent`, `tenure_months`, plus `prepay_amount` and `mode` for prepayment) and `result` (`emi`, `total_payment`, `total_interest`; or `emi_before/after`, `months_before/after/saved`, `interest_before/after/saved`). The numbers are computed by code, so show them as given. |

The recommendation's ranking, cover and premiums are computed by a deterministic engine, not by the language model, so the card is the source of truth. If `sample_data` is true the plans are fictional development data and must not be presented as real products.

### The needs analysis (recommendations)

Sahaj only recommends specific plans after it has understood the person. When the user asks which plan to buy, or how much cover they need, Sahaj requests `needs_analysis` consent, then asks one question per turn (goal, age, income, family, existing cover, health conditions where relevant, what matters most), reads everything back, and recommends **only after the user says yes**. Any correction restarts the confirmation. The user can ask to talk to a person at any point.

Frontend implications: keep the talk button available throughout, show the `profile_summary` card at the confirmation step, and render the `recommendation` card with its `disclosures`. Personal answers are not kept in the conversation record, so the `user` event text is the only copy: do not log it unnecessarily.

### Behaviour to design for

- **Answers come only from the loaded policy and loan documents.** If the answer isn't there, or the answer failed an automatic accuracy check, the user hears: "I can't confirm that from the documents I have. Would you like me to connect you to a person?" Offer the **talk to a human** button next to every answer.
- **Two failed checks in a row hand off to a human automatically** (`handoff` with reason `guardrail_failures`).
- **Recommendations come only from the needs analysis**, with the engine's ranking and disclosures. Outside it Sahaj explains and compares but does not tell the user which plan to choose, and it never pressures ("you must buy").
- **Plan-specific questions need a plan.** "What is the waiting period?" with no plan named is answered from the general explanations only. Name the plan, or ask after a comparison or recommendation (then it means those plans).
- **Go deeper:** the user just asks ("explain in more detail"). The server returns a longer answer with more clauses. There is nothing for the client to do.
- **Citations are never spoken.** The audio has them removed.
- Disable the talk button from sending until `done`, `error` or `handoff` arrives.
- Handle `ws.onclose`. Reconnect, and tell the user the conversation context was reset. Consent is per session today, so they will be asked again.
- Microphone access needs a secure context: `localhost` or HTTPS.
- The agent replies in the language the user spoke, in both text and voice. Mixed speech such as Hinglish is answered in Hindi.
  - **Full voice:** English, Hindi, Bengali, Tamil, Telugu, Kannada, Marathi, Gujarati, Punjabi, Malayalam, Odia.
  - **Voice through a related voice:** Nepali, Maithili, Dogri, Konkani, Sanskrit and Bodo (Hindi voice), Assamese (Bengali voice). Pronunciation is approximate.
  - **Text only:** Urdu, Kashmiri, Sindhi, Santali, Manipuri. No audio chunks arrive.

## Minimal client

```js
const ws = new WebSocket("ws://127.0.0.1:8000/ws/voice");
const send = (obj) => ws.send(JSON.stringify(obj));
let chunks = [];

ws.onmessage = ({ data }) => {
  if (data instanceof Blob) return chunks.push(data);                 // mp3 chunk
  const m = JSON.parse(data);
  if (m.type === "consent_required") send({ type: "consent", purpose: m.purpose, granted: confirm(m.text) });
  if (m.type === "user")      addMessage("user", m.text);
  if (m.type === "assistant") addMessage(m.agent, m.text, m.citations);
  if (m.type === "handoff")   showHandoff(m.reference);
  if (m.type === "error")     showError(m.message);
  if (m.type === "done" && chunks.length)
    new Audio(URL.createObjectURL(new Blob(chunks, { type: "audio/mpeg" }))).play();
  if (m.type === "done" || m.type === "error") chunks = [];
};

// push-to-talk
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const rec = new MediaRecorder(stream);
let parts = [];
rec.ondataavailable = (e) => parts.push(e.data);
rec.onstop = async () => { ws.send(await new Blob(parts).arrayBuffer()); parts = []; };
// button down: rec.start()    button up: rec.stop()
// human button: send({ type: "handoff" })
```

## Other endpoints

- `POST /stt`: multipart `file` (audio, up to 30 seconds). Returns `{"text","language"}`. Transcription only: no consent, masking or audit, so don't use it for user conversations.
- `GET /health`: `{"status":"ok"}`.
- **Workflow report** (admin key): `GET /audit/report/{session}?format=json|md|html` is a detailed report of what the orchestrator did in a conversation (intents, route, timings, tokens, cache hits, guardrail results, handoffs); `GET /audit/report` summarises recent sessions; `GET /audit/caches` shows live cache hit rates. See `docs/orchestration.md`.
- **Audit API** (back office only, header `X-Admin-Key`; disabled unless `ADMIN_API_KEY` is set):
  - `GET /audit/verify`: re-checks the tamper-evident chain. `intact:false` shows the first altered record.
  - `GET /audit/session/{session_id}`: consents, every turn and handoffs, in order.
  - `GET /audit/trace/{trace_id}`: one turn step by step (masked transcript, route, answer, guardrail verdict).

## Known limits (current version)

- **No user authentication.** A session is anonymous, and consent is tied to the socket session. Add login before real use. `/stt` and the WebSocket are open to anyone who can reach the server.
- No CORS configuration, so `fetch` to `/stt` from another origin is blocked until it is added.
- Push-to-talk only: no interrupting the agent and no automatic end-of-speech detection.
- Conversation history is in memory only. The audit ledger is SQLite for now (Postgres planned).
- Documents are **sample data** (`apps/api/knowledge/`). Answers are only as correct as the documents loaded.
- Questions the documents cannot answer, or answers the automatic checks cannot confirm, return "I can't confirm that…". In testing this is the intended outcome for questions that are related to a policy but not covered by it, and it also happens occasionally for answerable ones (the checks fail closed).
- Safari records mp4, not webm. Untested.

## Server setup (backend team)

The knowledge base lives in **Postgres with pgvector** (cosine similarity over multilingual embeddings). Embeddings are computed locally, so documents never leave your infrastructure.

```bash
docker compose up -d db            # from the repo root: Postgres 18 + pgvector (image pgvector/pgvector:pg18)
cd apps/api                        # everything below runs from apps/api
python3.12 -m venv .venv           # Python 3.12 is required (LangGraph and LangChain)
.venv/bin/pip install -r requirements.txt

# .env.local
SARVAM_API_KEY=...                 # required
ADVISORY_ENABLED=true              # kill switch: false = explain and compare only, never recommend
ADMIN_API_KEY=...                  # enables /audit
DATABASE_URL=postgresql://user:password@localhost:5432/sahaj   # default matches docker-compose.yml
HANDOFF_WEBHOOK_URL=https://...    # receives human-handoff packets (optional; handoffs are recorded either way)
SARVAM_CHAT_MODEL=...              # optional, default sarvam-105b-conversations

python -m rag.ingest               # load knowledge/*/*.md into pgvector (first run downloads a 2.2 GB model)
fastapi dev main.py
pytest tests                       # database tests skip if Postgres is unreachable
python tests/eval_retrieval.py     # retrieval accuracy; re-run after changing documents or the model
```

Documents are Markdown in `apps/api/knowledge/<domain>/` (`insurance`, `loan`). Each `## <clause-number> <title>` section is one citable clause, and its id is `<file-name>:<clause-number>`. Re-run `python -m rag.ingest` after editing: only changed clauses are re-embedded, and clauses you delete are removed so they can never be served. If the database is unreachable the app still starts, but every question returns an error instead of an answer.
