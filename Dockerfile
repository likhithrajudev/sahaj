# One image: the web app built with Node, served by the Python API at /app.
FROM node:22-alpine AS web
WORKDIR /repo
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages ./packages
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile --filter @sahaj/web... && pnpm --filter @sahaj/web build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 WEB_DIST=/app/web
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install -r requirements.txt
COPY apps/api/ .
COPY --from=web /repo/apps/web/dist /app/web
RUN useradd --uid 10001 --create-home sahaj && mkdir -p /data && chown sahaj /data
USER sahaj
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--ws-ping-interval", "20"]
