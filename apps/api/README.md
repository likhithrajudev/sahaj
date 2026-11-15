# @sahaj/api

FastAPI backend: voice WebSocket, STT, RAG over `knowledge/`, insurance/loan agents, trust layer (consent, PII, guardrails, audit).

Run everything from this directory (paths such as `static/`, `.env.local` and `ledger.db` are relative to it).

```bash
cd apps/api
python3.12 -m venv .venv   # 3.12 required (LangGraph) && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.local          # then fill in SARVAM_API_KEY
docker compose -f ../../docker-compose.yml up -d db
python -m rag.ingest                # load knowledge/ into pgvector
uvicorn main:app --reload           # http://127.0.0.1:8000
pytest tests
```

From the repo root: `pnpm dev:api`, `pnpm test:api` (with the venv active).
