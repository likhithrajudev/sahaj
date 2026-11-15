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

## Getting started

```bash
pnpm install
pnpm db:up                 # Postgres + pgvector
# backend setup (venv, .env.local, ingest): see apps/api/README.md
pnpm dev:api               # http://127.0.0.1:8000
pnpm dev:web               # http://localhost:5173 (proxies the API)
pnpm dev:mock              # UI work without Sarvam/Postgres: mock backend + web
pnpm demo:tunnel           # HTTPS URL for testing on an iPhone (mic needs HTTPS)
pnpm typecheck
```

- iPhone demo checklist: [`apps/web/README.md`](apps/web/README.md#demo-on-an-iphone)
- Deploying to Azure or AWS (single container): [`docs/deployment.md`](docs/deployment.md)

When the API protocol changes, update `docs/voice-api.md` and `packages/contracts` together.
