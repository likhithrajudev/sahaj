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

Metrics at `/metrics`, readiness at `/ready`; Prometheus, Grafana and LangSmith are described in [docs/observability.md](../../docs/observability.md).

From the repo root: `pnpm dev:api`, `pnpm test:api` (with the venv active).
