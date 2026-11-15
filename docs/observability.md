# Observability and the gateway layer

Three views of the same system: **LangSmith** (what the AI did on one turn), **Prometheus + Grafana** (how the service behaves over time) and the **gateway** (what every request goes through first). All settings are in `apps/api/.env.example`.

## Gateway layer (`apps/api/gateway/`)

Plain ASGI middleware around the whole app, so it covers REST, SSE and the WebSocket handshake.

| What | Behaviour |
|---|---|
| **Request id** | `X-Request-ID` is taken from the caller if it is 8-64 of `A-Za-z0-9._-`, else generated. It is echoed in the response, in error bodies (`request_id`) and in every access-log line. |
| **Rate limits** | Token bucket per client address and class: `/auth/*` 20/min, `/chat/*` and `/stt` 60/min, new voice sockets 30/min, everything else 300/min. Over the limit: `429` with `Retry-After` (a socket is refused before it is accepted). `/health`, `/ready` and `/metrics` are exempt. |
| **Body size** | Over `MAX_BODY_BYTES` (10 MB): `413`, also for chunked uploads with no `Content-Length`. |
| **Headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cross-Origin-Resource-Policy` on every response; `Cache-Control: no-store` on `/auth`, `/users`, `/admin` and `/chat`. HSTS and TLS belong to the proxy in front. |
| **Access log** | One line per request: method, path, status, ms, request id. The query string is never logged (a WebSocket token can be in it). `LOG_FORMAT=json` for log shipping. |
| **CORS** | Wraps the gateway, so a `429` or `413` still carries CORS headers and the browser shows the real error. |
| **Health** | `GET /health` = the process is up. `GET /ready` = the database answers (503 otherwise) and reports blob `storage` status: use it for load-balancer and orchestrator checks. |

Limits are held in memory, per process. With several workers each has its own buckets, so for a global limit use a shared store or limit at the load balancer. Set `TRUST_PROXY_HEADERS=true` only when a proxy really sits in front; otherwise anyone can pick their own address through `X-Forwarded-For`.

## Prometheus and Grafana

```bash
docker compose --profile observability up -d     # from the repo root
# Prometheus http://localhost:9090   Grafana http://localhost:3001 (admin / $GRAFANA_ADMIN_PASSWORD, default "admin")
```

The API exposes `GET /metrics`. Set `METRICS_TOKEN` to require a bearer token (then put it in `infra/prometheus/metrics_token` and uncomment the `authorization` block in `infra/prometheus/prometheus.yml`), and keep the endpoint off the public internet either way. The dashboard "Sahaj overview" and the alert rules are provisioned from `infra/`.

| Metric | Labels | Meaning |
|---|---|---|
| `sahaj_http_requests_total`, `sahaj_http_request_seconds` | method, route (template), status | Traffic and latency. |
| `sahaj_rate_limited_total` | limit | Refusals by the gateway. |
| `sahaj_ws_connections` | | Open voice sockets. |
| `sahaj_turns_total`, `sahaj_turn_seconds` | channel (voice, text), outcome (ok, error) | Conversation turns. |
| `sahaj_intents_total` | intent, source | What people ask for. |
| `sahaj_guardrail_total` | verdict, agent | Reply checks; anything but `pass` was blocked. |
| `sahaj_handoffs_total` | reason | Hand-offs to a person. |
| `sahaj_graph_node_seconds` | node | Time in each orchestrator node. |
| `sahaj_llm_calls_total`, `sahaj_llm_seconds`, `sahaj_llm_tokens_total` | purpose, cache, kind (input, output, cached) | Model use and prompt-cache share. |
| `sahaj_cache_total` | layer, result | Verified-answer cache. |
| `sahaj_auth_events_total` | event | Sign-ins, refreshes, rejected tokens, `refresh_reused`. |
| `sahaj_memory_events_total` | event | Memory saves. |
| `sahaj_cost_usd_total` | provider, kind, channel | Estimated spend in USD (model, speech-to-text, text-to-speech). |
| `sahaj_case_events_total` | event | Executive desk: cases opened or joined, claimed, released, messages, video KYC booked, resolved. |
| `sahaj_budget_events_total` | event | People warned near, or stopped at, their monthly limit. |
| `sahaj_file_events_total` | event | Uploads, downloads, deletions and rejected file types. |

Labels are small fixed sets. Nothing per-user, per-session or textual ever becomes a label. Alerts (`infra/prometheus/alerts.yml`): API down, 5xx above 5%, slow turns (p95 above 12 s), turn errors above 10%, guardrail blocks above 25%, refresh-token reuse, sustained rate limiting.

## LangSmith

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`. The test suite never traces, whatever `.env.local` says. Each turn is one trace named `sahaj_turn`: every orchestrator node and model call is a child run with timings and token counts (the model calls are named `llm:<purpose>` and tagged `provider:openai` or `provider:sarvam`). Tags: `env:`, `channel:`, `lang:`, `memory`. Metadata: `session_id`, `audit_trace_id` (the id in Sahaj's own audit trail, so a LangSmith trace can be matched to `/audit/trace/{id}`), `user_ref` (a salted hash: never the user id or email), language, channel, environment.

**Privacy.** LangSmith is a separate service, so traces leave your infrastructure. For that reason it is off by default, and when on it receives **no prompt or reply text** (`LANGSMITH_HIDE_IO=true`): only the shape, timings and tokens. Set it to `false` only with a data-processing agreement in place and after checking what the compliance team accepts. Even then, the text is already masked for PII, but it includes retrieved policy clauses and, for users with memory, background about them. Use `LANGSMITH_ENDPOINT` for the EU or a self-hosted LangSmith.
