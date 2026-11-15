# Sahaj Voice API: frontend integration guide

> Every response carries `X-Request-ID` (quote it in bug reports). Calls can be refused with `429` (`Retry-After` says how long to wait) or `413`. See [observability.md](observability.md) for the limits.

Talk to Sahaj by voice about insurance policies and loan offers. The client records the user's speech and sends it. The server replies with the transcript, a cited text answer and the answer as spoken audio. Sahaj routes each question to an insurance or loan specialist, and every turn passes consent, PII masking, answer-checking guardrails and an audit trail.

- **Voice endpoint:** `ws://127.0.0.1:8000/ws/voice` (use `wss://` in production)
- **Streaming voice endpoint:** `ws://127.0.0.1:8000/ws/voice/stream` (use `wss://` in production)
- **Interactive REST docs:** `http://127.0.0.1:8000/docs`
- **Sign-in required:** see [Authentication](#authentication)
- **Try it by hand:** run the API and open `http://127.0.0.1:8000/test/` (a test console covering sign-in, chat over WebSocket or SSE, memory, files and feedback)

## Streaming microphone sessions

`/ws/voice/stream` keeps one authenticated voice session open while the client sends binary audio chunks. The client sends `{"type":"audio_end"}` at each speech boundary; Sahaj transcribes and responds, then accepts the next segment on the same connection. `{"type":"audio_cancel"}` discards the current segment. Chunks for one segment must belong to the same WebM/Opus recording, and each segment is capped at `MAX_UPLOAD_BYTES`.

This protocol lets a client use voice activity detection and keep the microphone open without a press-and-hold key. Microphone permission and speech-boundary detection run in the client; the existing `/test/` console still uses `/ws/voice` and has not been changed.

## Talking to a person (customer executive desk)

Some conversations need a person: when the customer asks, when they complain or are in distress, when Sahaj keeps failing or keeps having to ask what they mean, and to arrange video KYC. The request becomes a **case** on the executive desk, carrying the masked conversation so far. For V-CIP, the authorised official of the regulated entity conducts the live identity check; Sahaj's current implementation schedules an appointment but does not conduct or verify the session.

**Customer side, on the socket**
- `{"type":"handoff"}` (the "talk to a person" button), or with `"reason":"video_kyc"|"callback"|"complaint"` and an optional `"note"`. Video KYC needs the `video_kyc` consent first (otherwise you get `consent_required`).
- You get `{"type":"handoff","reference","reason","case":{"id","reference","kind","status":"waiting"|"with_executive","priority"}}`. **From then on, `text` and audio go to the executive, not the AI**; while nobody has picked it up you get `status: waiting_for_executive`.
- Then: `agent_joined` (`agent.name`), `agent_message` (`text`, `agent`, `at`), `agent_left` (back in the queue), `video_kyc_scheduled` (`scheduled_for`, `meeting_url`), and `handoff_closed` (`status`: `resolved` or `cancelled`, optional `message`), after which the AI answers again.
- `{"type":"handoff_cancel"}` withdraws the request.
- The `session` event's `case` field is the open case, if any, so a reconnecting customer goes straight back to their executive.
- Escalation is automatic for complaints (priority high) and distress (urgent): Sahaj acknowledges in one fixed sentence and hands over at once.

**Customer side, over REST:** after `PUT /consents/video_kyc` with the version shown by `GET /consents`, call `POST /cases` (`{"kind":"video_kyc"|"callback"|"complaint"|"help","note"}`). Also: `GET /cases` (their cases and the active thread), `POST /cases/{id}/messages`, `POST /cases/{id}/cancel`. A person has at most one open case; asking again adds to it, and a more serious reason raises its priority.

**Executives** (role `executive`, granted by an admin with `PATCH /admin/users/{id}/role`):
- `WS /ws/desk?access_token=…`: a `queue` snapshot, then `case_opened`, `case_updated`, `customer_message`, `case_claimed`, `case_released`, `case_closed`.
- `GET /desk/queue?view=open|mine|overdue|all` (by priority then age, with pick-up deadlines: urgent 5 min, high 30, normal 120) and `GET /desk/cases/{id}` (reason, the masked conversation before it, the thread, the customer's name, contact, language, consents and whether they are online, and the audit `trace_id`).
- `POST /desk/cases/{id}/claim` (409 if someone was first), `/release`, `/messages` (`{"text"}`), `/video-kyc` (`{"scheduled_for": "<ISO time with zone>", "meeting_url": "https://…"}`), `/resolve` (`{"outcome": "resolved"|"escalated_offline"|"no_response"|"duplicate", "resolution", "message"}`).
- Customer messages reach executives masked (`[PAN_1]`, `[PHONE_1]`). Every claim, release, booking and close is written to the audit ledger with who did it.

## Usage and spending limit

Every model call, speech-to-text request and text-to-speech request a person causes is recorded with its estimated cost in US dollars. Each person may spend **$5 a month** by default (calendar month, UTC); an admin can change it per person.

- **Which model answers:** voice conversations go through Sarvam end to end (speech-to-text, the answer, and speech). Typed conversations (socket `text` messages and `/chat/stream`) are answered by OpenAI (`gpt-4o-mini`), whose prompt cache is shared across users: in testing, 57% of input tokens on a second question came from it. The knowledge base is searched with OpenAI embeddings either way.
- `GET /users/me/usage`: `budget_usd`, `spent_usd`, `remaining_usd`, `percent_used`, the period (`start`, `resets_at`), token totals, call and unit counts by kind, and the spend `by_provider`, `by_kind` (llm, stt, tts, embedding, ocr, websearch), `by_purpose` and `by_channel`. `estimate: true`: figures come from configured prices, not an invoice. Firecrawl cost is recorded using `FIRECRAWL_PRICE_PER_SEARCH_USD`.
- **Near the limit** (80%), the socket sends `{"type":"usage_warning","spent_usd","budget_usd","percent_used"}` once per conversation.
- **Over the limit**, a turn is refused before anything is spent: `{"type":"budget_exceeded","spent_usd","budget_usd","resets_at"}` followed by an `error`. Show when it renews.
- **Admins:** `GET /admin/usage` (this month's top spenders), `PATCH /admin/users/{id}/budget` with `{"budget_usd": 10}` (or `null` for the default).
- If speech synthesis fails, the written reply still arrives, followed by `{"type":"status","stage":"speech_unavailable"}` and `done`.

## Consent

Consent belongs to the **signed-in person**, not to a connection: grant it once and it carries over to later conversations, until it expires (365 days) or the consent text changes. Everything a consent screen needs is in one API:

| Call | Purpose |
|---|---|
| `GET /consents` | Every purpose: `purpose`, `title`, `text` (show verbatim), `version`, `required`, `requires`, `withdrawal` (what withdrawing does, for the confirm dialog), `granted`, `granted_at`, `expires_at`, and `action`: `ask` (never decided or withdrawn), `renew` (expired, or the text changed) or `none`. `missing_required` lists what must be granted before Sahaj can be used (`conversation`). |
| `PUT /consents/{purpose}` | `{"granted": true, "version": "<the version you showed>"}` or `{"granted": false}`. Granting **requires** `version`, so the record proves which text was agreed to. |
| `GET /consents/history?purpose=` | The person's own record, oldest first: event, version, text hash, channel, request id, expiry. |

Behaviour to design for:
- **Stale text.** If `version` is not the current one, you get `409` with `detail.code = "stale_version"` and `detail.current` (the new text and version): show it and ask again.
- **Dependencies.** `needs_analysis` needs `conversation`; `document_analysis` needs `documents`. Granting without the prerequisite is a `409` (`code: "requires"`, `purpose` names what is missing). **Withdrawing a purpose also withdraws the ones that depend on it**; the response's `withdrawn` lists them all.
- **Withdrawal erases.** `memory` erases remembered data, `documents` deletes every stored file, `document_analysis` erases what was learned from the PDFs, `needs_analysis` and `conversation` forget the details held in the conversation. The response's `erased` says what was removed. If erasing fails, the withdrawal still stands and you get a `500` with `code: "erasure_failed"`: withdraw again to retry.
- **Sockets.** `consent_required` events carry `purpose`, `title`, `version`, `text`, `required`, `requires` and `withdrawal`. Answer with `{"type":"consent","purpose":"...","granted":true,"version":"<event.version>"}`. A `version` that is not current gets an `error` and a fresh `consent_required`. Withdrawing sends a `consent` event with `status: "revoked"` for every purpose it took with it. Without a `version` the grant is still accepted but recorded as *unconfirmed*.
- **Withdrawn elsewhere.** If a person withdraws from settings while a conversation is open, the conversation drops what it held on the next message and asks again if `conversation` is gone.
- The older endpoints (`PUT /files/consent`, `PUT /files/analysis/consent`, `PUT /users/me/memory/consent`) still work and write the same record.

## Authentication

Sahaj signs people in with Google and then uses its own JWTs. `/ws/voice`, `/users/*` and `/admin/*` need an access token. `/health` and `/auth/*` do not.

1. The client signs in with Google (Google Identity Services on web, the Google SDK on Android/iOS) and gets an **ID token**. Its OAuth client id must be listed in the server's `GOOGLE_CLIENT_IDS`.
2. `POST /auth/google` with `{"id_token": "...", "platform": "web"|"android"|"ios"}` returns `{access_token, refresh_token, token_type, expires_in, user}`. The account is created on first sign-in.
3. Send `Authorization: Bearer <access_token>` on REST calls. The access token lives for 15 minutes.
4. When it expires, `POST /auth/refresh` with `{"refresh_token": "..."}` returns a new pair. **A refresh token works once**: store the new one every time. Reusing an old one signs that device out everywhere.
5. `POST /auth/logout` with the refresh token signs the device out (204).

`GET /auth/config` returns the public API base URL, Google web client ID and authorized JavaScript origin. The local console uses `http://127.0.0.1:8000` as its origin. This is an ID-token flow: there is no redirect URI to register in Google Cloud Console. For production, set `PUBLIC_API_URL` to the API's public origin and register that origin as an authorized JavaScript origin on the Google **Web application** client. Register each scheme/host/port that serves a web client; do not add `/auth/google` as a redirect URI.

**WebSocket.** Browsers cannot set headers on a WebSocket, so connect with `ws://.../ws/voice?access_token=<access_token>` (non-browser clients can send the `Authorization` header instead). If the token is missing, invalid or expired the server closes the socket with code **4401**: refresh the token and reconnect. Check the token is fresh before connecting, because URLs are logged.

| Endpoint | Purpose |
|---|---|
| `GET /users/me` | The profile (`id, email, name, picture, language, platform, role`) and `memory_consent`. |
| `PATCH /users/me` | Update `name`, `language` (for example `hi-IN`) or `platform`. |
| `GET /languages` | Supported Indian language tags and whether native or borrowed speech output is available. |
| `DELETE /users/me` | Delete the account, its sign-ins and everything remembered (204). |
| `GET /admin/users`, `PATCH /admin/users/{id}/role` | Admin only. Roles are `user` and `admin`. |

## Files

Signed-in users can store documents (a loan offer, a policy). Files are private: they sit in a private Amazon S3 bucket, there are no shareable links, and only the owner can download them through the API.

1. `GET /files` returns the user's files, the `limits` and `consent_text`. Show the text verbatim, then `PUT /files/consent` with `{"granted": true}`. Uploads return `403` until then.
2. `POST /files` (multipart field `file`) stores one PDF, PNG, JPEG, WebP, GIF, DOCX, XLSX, PPTX, UTF-8 text or supported audio file, up to `limits.max_bytes`, at most `limits.max_files` per person. The type is decided by the file's contents, not its name or declared type (`415` otherwise; `413` too large; `409` at the file limit; `503` if storage is not set up). The response is the file record.
3. `GET /files/{id}` downloads it (as an attachment), `DELETE /files/{id}` removes it (204). Another person's id is a `404`.
4. Withdrawing consent (`granted: false`) or deleting the account **deletes every stored file**.

### Asking questions about your own documents

A second consent, `document_analysis`, lets Sahaj read uploaded PDFs, photos (PNG, JPEG), DOCX, XLSX, PPTX and UTF-8 text so questions can be asked about them. PDFs with a text layer and office/text files are parsed locally; scanned PDFs and photos are read by Sarvam OCR, up to `DOC_MAX_PAGES` pages, slides or sheets. WebP, GIF and audio files can be stored but are not indexed for document questions.

1. `GET /files` returns `analysis_consent` and `analysis_consent_text`. Show the text verbatim, then `PUT /files/analysis/consent` with `{"granted": true}` (needs the `documents` consent first). That reads the PDFs already stored; new uploads are read straight away.
2. Each file's `index_status` goes `indexing` then `ready` (or `empty`, `unsupported`, `over_budget` when the person's monthly limit is used up, or `failed`). Poll `GET /files` until it is `ready`. OCR pages and embeddings are charged to the person (`by_kind.ocr`, `by_channel.documents` in `/users/me/usage`).
3. Then just ask in chat, for example *"What is the prepayment charge in my offer?"* or *"What is the total on my hospital bill?"*. Answers cite the person's own passages as `mydoc-<id>:p<page>.<n>`, and `structured.sources[].text` begins with the file name and page. Identifiers such as PAN, Aadhaar, phone and account numbers are masked **before** a passage is stored or shown to the AI model (Sarvam's OCR, which reads the image, sees the page as it is: the consent text says so).
4. Withdrawing `document_analysis` forgets everything learned (the files stay). Withdrawing `documents` or deleting the account removes it all. Replies that used a person's documents are never cached or shared.

`GET /files` is the signed-in person's inventory. It returns only their records, and `GET /files/{id}` streams an owner-checked file; another person's file ID returns `404`. Files live in private S3 storage with owner-specific prefixes and are never exposed through public or presigned URLs. SDK methods are `files()`, `uploadFile()`, `downloadFile()` and `deleteFile()`.

Sahaj does not virus-scan uploaded files.

## Calculators and financial actions

- `POST /calculators/emi` accepts `principal`, `annual_rate_percent` and `tenure_months`; `POST /calculators/prepayment` adds `prepay_amount` and optional `mode` (`reduce_tenure` or `reduce_emi`). Both require sign-in, return deterministic calculations with a reducing-balance disclosure, and reject out-of-range inputs. They are estimates, not lender quotes.
- `GET /financial/providers` lists installed credit-bureau, lender and insurer adapters. `POST /financial/credit-check` requests an actual provider credit check after the person sees and grants the versioned `credit_bureau` consent and confirms the selected provider. It does not derive a CIBIL score from a formula. With no authorised adapter configured it returns `503 provider_unavailable`.
- `POST /financial/loan/offers` requires a recent credit check from the same provider plus `financial_application` consent. The person reviews the lender's offer and Key Facts Statement (KFS), then `POST /financial/loan/apply` submits only after explicit KFS acceptance and final confirmation. A lender makes the decision.
- `POST /financial/insurance/quotes` gets insurer quotes. The person reviews actual policy terms, then `POST /financial/insurance/purchase` submits the selected quote and accepted terms version after confirmation. Payment and issuance remain with the insurer/provider checkout flow.
- `GET /financial/events` returns only the signed-in person's provider references and statuses. SDK methods include `checkCredit()`, `loanOffers()`, `applyForLoan()`, `insuranceQuotes()`, `purchaseInsurance()` and `financialEvents()`.

There are plugin points, not production financial partners in this checkout. These calls fail closed until an authorised adapter is installed; Sahaj does not invent scores, offers, approvals, quotes or policies.

## Web research

`POST /search/web` (`{ "query": "...", "domain": "insurance"|"loan" }`) runs an India-focused Firecrawl search and returns the result title, URL, excerpt, page content and usage. `/search/insurance` remains as the insurance-only alias. The assistant can use web research when approved local documents do not answer a public market-information question; those responses carry `web:*` citations. A search result is research evidence, not an insurer/lender offer or a personalised approval decision.

## Memory

With the person's **`memory` consent**, Sahaj remembers a short summary of each conversation and a few preferences (language, topics, goals, answer style) and uses them in later conversations. It never stores numbers, identifiers, contact or health details. Unlike the other consents, `memory` belongs to the person, not to one conversation.

- Ask for it like any other consent: send `{"type":"consent","purpose":"memory","granted":true}` on the socket, or `PUT /users/me/memory/consent` with `{"granted": true}`. Show the consent text verbatim: `GET /users/me/memory` returns it as `consent_text`.
- The `session` event says whether memory is in use (`"memory": true`). Memory is written when the socket closes.
- `GET /users/me/memory` lists everything remembered. `DELETE /users/me/memory/{id}` removes one item and `DELETE /users/me/memory` removes all of it.
- Withdrawing consent (`granted: false`, on the socket or over REST) **erases all remembered data**.

## Text chat and streaming

The reply **text is not streamed token by token**: every reply is checked by the guardrails and a fact-check before anyone sees it, so it arrives whole. What you can stream is progress and audio:

- `{"type":"status","stage":"transcribing"|"thinking"|"checking"|"speaking"}` events during a turn (use them for a typing indicator). `transcribing` is voice only; `speaking` only when audio follows.
- The audio reply arrives as binary MP3 chunks, so playback can start before the last chunk.

**Typed messages** on the socket: `{"type":"text","text":"...","language":"hi-IN","speak":false}`. It takes the same path as speech (same consent, masking and checks) and gets the same events minus the audio, which is sent only when `speak` is true. `language` defaults to the profile language.

**Plain HTTP for text clients.** `POST /chat/stream` is the same protocol as a Server-Sent Events stream, for clients that cannot hold a WebSocket:

```
POST /chat/stream      Authorization: Bearer <access_token>
{"message": {"type":"text","text":"What is the waiting period?"}}          (no session_id: starts a conversation)
→ data: {"type":"session","id":"...","user":{...},"memory":false}
→ data: {"type":"consent_required","purpose":"conversation",...}            show it, then:

POST /chat/stream
{"session_id":"...","message":{"type":"consent","purpose":"conversation","granted":true}}
→ data: {"type":"consent","purpose":"conversation","status":"granted"}

POST /chat/stream
{"session_id":"...","message":{"type":"text","text":"What is the waiting period?"}}
→ data: {"type":"user",...}  {"type":"status",...}  {"type":"assistant",...}  {"type":"done"}
```

Each `data:` line is one of the WebSocket events below, and the stream ends when the turn is finished. `message` accepts `text`, `consent` and `handoff`. On text messages only, `/help`, `/usage`, `/clear`, and `/language <code>` are handled as shortcuts without a model call; they do not run on audio turns. Conversations are kept for 30 minutes of inactivity (at most 5 per person); an unknown or expired `session_id` returns 404, so start a new one. `DELETE /chat/{session_id}` ends one and saves memory if allowed. Sessions live in one server process, so run a single worker or route a session's requests to the same one.

### Live insurance search

When the user asks for current insurers, products, or insurance platforms, typed chat can search Firecrawl's `/v2/search` using India-focused web and news results, then return source-tagged claims with URLs. Set `FIRECRAWL_API_KEY` to enable it. `POST /search/insurance` offers the same search to authenticated clients with `{"query":"health insurance platforms in India","limit":5}`. Queries are PII-masked before they leave Sahaj. Search calls and Firecrawl credits are counted as `websearch` in the user's ledger; configure `FIRECRAWL_PRICE_PER_CREDIT_USD` for estimated provider cost and budget enforcement. The direct endpoint returns 503 when Firecrawl is not configured and 502 when Firecrawl is unavailable.

## Trust badge and follow-ups

Every `assistant` event also carries:

- `verification`: `{level, sources, from_cache, checks}`. `level` is `verified` (each statement tied to a source and fact-checked), `engine` (built from the recommendation or calculation engine's own figures), `checked` (screened by the guardrails, nothing to cite) or `blocked` (the draft failed the checks, so a safe reply was shown). Show it as a badge.
- `suggestions`: up to three follow-up questions to show as chips; send one back as a `text` message. Empty while Sahaj is itself asking a question or after a person has taken over.

**Rating replies.** `POST /feedback` with `{"trace_id": "<the reply's trace_id>", "rating": "up"|"down", "comment": "..."}` (204). One rating per person per reply; rating again replaces it. A comment is stored with personal identifiers masked. Admins review ratings at `GET /admin/feedback`, and each carries the `trace_id` for `/audit/trace/{id}`.

**Download my data.** `GET /users/me/export` returns profile, consent history, memory, the file list and the person's ratings as one JSON download.

## Structured replies

Every `assistant` event carries `structured` next to `text`, so a UI can render a reply as a headline, a list of statements and source chips without parsing tags:

```json
{"type":"assistant","agent":"insurance","text":"The waiting period is 30 days. [doc:1.1] Cover is up to 1.5 lakh. [doc:2.3]",
 "structured":{"kind":"answer","summary":"The waiting period is 30 days.",
   "points":[{"text":"The waiting period is 30 days.","sources":["doc:1.1"]},{"text":"Cover is up to 1.5 lakh.","sources":["doc:2.3"]}],
   "sources":[{"id":"doc:1.1","text":"..."},{"id":"doc:2.3","text":"..."}],
   "notes":["Premiums are indicative."]}}
```

It is the same verified text, split and labelled: nothing is added or reworded. `notes` holds fixed text such as disclosures. For recommendations and comparisons the `card` event still carries the figures, and `structured` carries the narration. `kind` tells you how to style it (`ask` is a question to the user).

## Session flow

```
connect    ← {"type":"session","id":"...","user":{...},"memory":false}
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
| **Text (JSON)** | `{"type":"consent","purpose":"...","granted":true\|false,"version":"..."}`: grant or withdraw consent (`version` = the version shown; see [Consent](#consent)). |
| | `{"type":"text","text":"...","language":"en-IN","speak":false}`: a typed message (see [Text chat](#text-chat-and-streaming)). |
| | `{"type":"handoff"}`: the **talk to a human** button. Send it any time. |

## Server → client (JSON text frames)

| `type` | Fields | What to do |
|---|---|---|
| `session` | `id`, `user`, `memory` | `id` is the session reference for support requests. `user` is the signed-in profile and `memory` says whether remembered context is in use. |
| `status` | `stage` | Progress of the current turn: `transcribing`, `thinking`, `checking`, `speaking`, or `speech_unavailable` (the written reply is complete; the spoken one failed). No content. |
| `usage_warning` | `spent_usd`, `budget_usd`, `percent_used` | The person has used 80% of this month's allowance. |
| `budget_exceeded` | `spent_usd`, `budget_usd`, `resets_at` | The allowance is used up; the message was not processed. |
| `handoff` | `reference`, `reason`, `case` | A person is now handling the conversation (see [Talking to a person](#talking-to-a-person-customer-executive-desk)). |
| `agent_joined`, `agent_message`, `agent_left`, `video_kyc_scheduled`, `handoff_closed` | see that section | Events from the executive desk. |
| `consent_required` | `purpose`, `title`, `version`, `text`, `required`, `requires`, `withdrawal` | Show `text` exactly as sent with accept and decline buttons, then reply with a `consent` message that echoes `version` (see [Consent](#consent)). No audio is processed until `conversation` is granted. A second purpose, `needs_analysis`, is requested the first time the user asks for a recommendation: it covers using their age, income, family and existing cover. If they decline, Sahaj still explains and compares plans but will not ask for or use personal details. |
| `card` | `kind`, `card`, `trace_id` | Structured data to render as UI, sent just before the matching `assistant` message. See "Cards" below. Always trust the card over the spoken text for figures. |
| `consent` | `purpose`, `status` | Confirms `granted` or `revoked`. After `revoked` the server forgets what that purpose allowed it to hold (one event per purpose withdrawn, including dependents). |
| `user` | `text` | The transcript as a user message. **Personal identifiers are already masked** (for example `[PAN_1]`, `[PHONE_1]`). Show it as is. |
| `assistant` | `agent`, `text`, `citations`, `structured`, `trace_id` | The answer. `structured.points[].sources` contains source IDs for each claim and `structured.sources[]` maps those IDs to source text. The top-level `citations` field contains the same source entries. Render source tags from structured points against `structured.sources`; keep `trace_id` for support. |
| *(binary)* | | MP3 chunks of the spoken answer. Join them in order. |
| `done` | none | The turn is finished. If you received no audio chunks, play nothing. Some languages are text only. |
| `handoff` | `reference`, `reason` | A human is taking over. Show the `reference` to the user and disable the talk button. The AI stops answering on this session. `reason` is `user_requested`, `guardrail_failures` (two answers in a row could not be verified) or `stuck_in_questions` (three turns of the needs analysis made no progress). |
| `error` | `message` | The turn failed (silence, bad audio, upstream failure). No `done` follows. The socket stays open, so let the user try again. |

### Cards

| `kind` | When | Contents |
|---|---|---|
| `profile_summary` | The needs analysis is asking the user to confirm | `details`: the complete list of what Sahaj understood, as short lines. **Display it.** The spoken read-back can be shorter, and the user must see exactly what will be used before saying yes. |
| `recommendation` | After the user confirms | `suggested_cover` (`amount`, `basis`, `note`), `plans` (ranked; each with `name`, `insurer`, `cover`, `annual_premium`, `highlights`, `reasons`, `criteria` showing how it scored), `disclosures` (all of them, always show), `sample_data`, `indicative_premiums`. |
| `comparison` | The user asks to compare plans | `plans`, each with `rows` of `[label, value]` pairs: render as a table. |
| `calc` | A loan calculation (EMI, or interest saved by prepaying) | `kind` (`emi` or `prepayment`), `inputs` (what the user gave) and `result`. The numbers are computed by code, so show them as given. |

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

- **`/stt` is open.** The WebSocket, chat, files and consent need a sign-in, but `POST /stt` still accepts anyone who can reach the server.
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
