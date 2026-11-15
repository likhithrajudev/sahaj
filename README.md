# Sahaj - your AI companion

Monorepo (pnpm workspaces).

```
apps/
  api/          @sahaj/api        FastAPI backend (Python): voice, RAG, agents, trust layer
  web/          @sahaj/web        Mobile-first PWA (React + Vite)
packages/
  contracts/    @sahaj/contracts  Shared TypeScript types for the API / WebSocket protocol
docs/                             Product and API docs
docker-compose.yml                Local Postgres + pgvector
```

## Run locally

One-time setup:

```bash
pnpm install
pnpm db:up                                        # Postgres 18 + pgvector (docker)
cd apps/api && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.lock && cd ../..
cp apps/api/.env.example apps/api/.env.local      # then fill in, at least:
#   SARVAM_API_KEY   speech-to-text, voice answers, text-to-speech
#   OPENAI_API_KEY   knowledge-base embeddings, typed replies (suggestion chips)
#   JWT_SECRET       any 32+ random characters (openssl rand -hex 32)
#   DEV_LOGIN=true   sign in without Google on this machine (ENVIRONMENT=development)
#   GOOGLE_CLIENT_IDS (optional) a web OAuth client id for the real Google button
```

Every time:

```bash
pnpm dev:api        # http://127.0.0.1:8000 (fills the knowledge base on first start; check http://127.0.0.1:8000/ready)
pnpm dev:web        # http://localhost:5173  -> sign in with "Developer sign-in", agree, hold to talk
```

Other modes:

```bash
pnpm tunnel         # HTTPS link for a phone (the mic needs HTTPS)
pnpm test:api       # backend tests (run from apps/api so .env.local applies)
pnpm typecheck
```

Over a tunnel, the dev login is reachable by anyone with the link (the API sees the request coming from Vite on
this machine). Use a Google client id instead when sharing the link outside the team.

- Testing on an iPhone: [`apps/web/README.md`](apps/web/README.md#testing-on-an-iphone)
- Deploying to Azure or AWS (single container): [`docs/deployment.md`](docs/deployment.md)

When the API protocol changes, update `docs/voice-api.md` and `packages/contracts` together.
