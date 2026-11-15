# Sahaj - your AI companion

Monorepo (pnpm workspaces).

```
apps/
  api/          @sahaj/api        FastAPI backend (Python): voice, RAG, agents, trust layer
  web/          @sahaj/web        Frontend (to be scaffolded)
packages/
  contracts/    @sahaj/contracts  Shared TypeScript types for the API / WebSocket protocol
  sdk/          @sahaj/sdk        Typed Node.js SDK and plugin interfaces for integrations
docs/                             Product and API docs
docker-compose.yml                Local Postgres + pgvector
```

## Getting started

```bash
pnpm install
pnpm db:up                 # Postgres + pgvector
# backend setup (venv, .env.local, ingest): see apps/api/README.md
pnpm dev:api               # http://127.0.0.1:8000
pnpm typecheck
```

When the API protocol changes, update `docs/voice-api.md` and `packages/contracts` together.

Build the SDK with `pnpm --filter @sahaj/sdk build`; it is configured for public scoped npm publishing after build.
