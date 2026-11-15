# @sahaj/api

FastAPI backend: Google sign-in + JWT accounts, a customer executive desk (human in the loop), per-user memory, voice WebSocket, STT, RAG over `knowledge/`, insurance/loan agents, trust layer (consent, PII, guardrails, audit).

Run everything from this directory (paths such as `.env.local` and `ledger.db` are relative to it).

```bash
cd apps/api
python3.12 -m venv .venv   # 3.12 required (LangGraph) && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.local          # then fill in OPENAI_API_KEY, SARVAM_API_KEY, JWT_SECRET and GOOGLE_CLIENT_IDS
docker compose -f ../../docker-compose.yml up -d db
python -m rag.ingest                # load knowledge/ into pgvector (also done on startup)
uvicorn main:app --reload           # http://127.0.0.1:8000
pytest tests
```

**Test console:** with `DEV_LOGIN=true` in `.env.local`, run the API and open http://127.0.0.1:8000/test/ and sign in with any email. The knowledge base fills itself on startup (`AUTO_INGEST`, OpenAI embeddings: there is no model to download); `/ready` shows whether it is usable.

For Google sign-in, create a **Web application** OAuth client. Add `http://127.0.0.1:8000` as an authorized JavaScript origin for this local console, then put its client ID in `GOOGLE_CLIENT_IDS`. This app uses Google Identity Services to send an ID token to `POST /auth/google`; it has no OAuth redirect URI. In production, set `PUBLIC_API_URL` to the public API origin and add that origin (scheme and host only) to the web client. The `/test/` console is only served when `ENVIRONMENT=development` and `TEST_PAGE=true`.

Set `FIRECRAWL_API_KEY` to enable current insurance and loan web search in typed chat and through `POST /search/web`. `GET /languages` lists supported locale tags. Typed chat can also use `/help`, `/usage`, `/clear`, `/cancel`, `/inventory`, `/inventory show`, and `/language <code>`; these shortcuts do not run on voice turns.

Financial partner modules are configured with `FINANCIAL_PROVIDER_MODULES`. Without an installed, authorised provider, credit checks, quotes, applications and purchases return an unavailable response; no score, offer, approval or policy is simulated. See [financial integrations](../../docs/financial-integrations.md).

Metrics at `/metrics`, readiness at `/ready`; Prometheus, Grafana and LangSmith are described in [docs/observability.md](../../docs/observability.md).

From the repo root: `pnpm dev:api`, `pnpm test:api` (with the venv active).
