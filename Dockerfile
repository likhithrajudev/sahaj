# syntax=docker/dockerfile:1
# One image: FastAPI serves the API, the voice WebSocket, the built PWA (at /) and the console (at /app)
# from the same origin.
#   docker build -t sahaj .
# Embeddings come from OpenAI (OPENAI_API_KEY), so no model is downloaded or baked in.

# ---------- web: build the PWA and the console ----------
FROM node:22-slim AS web
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages/contracts/package.json packages/contracts/
COPY apps/web/package.json apps/web/
COPY apps/console/package.json apps/console/
RUN pnpm install --frozen-lockfile --filter "@sahaj/web..." --filter "@sahaj/console..."
COPY packages/contracts packages/contracts
COPY apps/web apps/web
COPY apps/console apps/console
RUN pnpm --filter @sahaj/web build && pnpm --filter @sahaj/console build

# ---------- api: Python runtime ----------
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Pinned, resolved set (regenerate with: pnpm --filter @sahaj/api lock). uv is much faster than pip and
# avoids pip's resolver backtracking through hundreds of langchain-core versions.
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv
COPY apps/api/requirements.lock .
RUN uv pip install --system --no-cache -r requirements.lock

COPY apps/api/ .
COPY --from=web /repo/apps/web/dist /app/web
COPY --from=web /repo/apps/console/dist /app/console

# The audit ledger is SQLite for now: mount a persistent volume at /data or it is lost on every restart.
ENV WEB_DIST=/app/web CONSOLE_DIST=/app/console LEDGER_DB=/data/ledger.db
RUN useradd --system --create-home --uid 1001 sahaj && mkdir -p /data && chown -R sahaj /data /app
USER sahaj

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
# --proxy-headers: trust X-Forwarded-Proto from the load balancer (Azure Container Apps / AWS ALB terminate TLS).
# --ws-ping-interval: keeps idle voice sockets alive through load-balancer idle timeouts (ALB default 60 s).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--ws-ping-interval", "20", "--ws-ping-timeout", "20"]
