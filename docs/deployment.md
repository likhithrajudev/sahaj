# Deploying Sahaj (Azure or AWS)

Sahaj ships as **one container** (root `Dockerfile`): FastAPI serves the API, the voice WebSocket and the built PWA
from the same origin. The load balancer only needs to terminate HTTPS and pass WebSockets through. Because
everything is on one origin, the browser gets `wss://` automatically and no CORS setup is needed.

```
 iPhone / browser ──HTTPS + WSS──►  Load balancer (TLS)  ──►  sahaj container :8000  ──►  Postgres + pgvector
                                                                   │  /            PWA (apps/web/dist)
                                                                   │  /ws/voice    voice socket
                                                                   │  /stt /health /audit /docs
                                                                   └─ /data/ledger.db  (persistent volume)
```

## Build

```bash
docker build -t sahaj .                                   # bakes the 2.2 GB embedding model in (recommended)
docker build -t sahaj --build-arg BAKE_MODEL=false .      # smaller image; downloads the model on every cold start
```

Baking the model makes the image about 3.5 GB, but startup is fast and needs no outbound download. Run a single
image for amd64 hosts: `docker buildx build --platform linux/amd64 -t <registry>/sahaj:<tag> --push .` (Apple
Silicon builds arm64 by default, which Azure and Fargate amd64 tasks cannot run).

## Configuration

| Variable | Required | Notes |
|---|---|---|
| `SARVAM_API_KEY` | yes | Store as a secret (Key Vault / Secrets Manager) |
| `DATABASE_URL` | yes | `postgresql://user:pass@host:5432/sahaj?sslmode=require` |
| `ADMIN_API_KEY` | recommended | Enables `/audit` (disabled when unset) |
| `HANDOFF_WEBHOOK_URL` | optional | Receives human-handoff packets |
| `ADVISORY_ENABLED` | optional | `false` = explain and compare only, never recommend |
| `LEDGER_DB` | preset | `/data/ledger.db`. **Mount persistent storage at `/data`** |
| `CORS_ORIGINS` | no | Only if the web app is hosted on a different origin |

Health check: `GET /health`. The container loads the embedding model at startup, so allow a **startup grace
period of about 120 s** before health checks count.

## Database

Postgres 15+ with the `vector` extension. The app runs `CREATE EXTENSION IF NOT EXISTS vector` and creates its
table itself, but managed services must allow the extension first:

- **Azure Database for PostgreSQL (Flexible Server):** add `VECTOR` to the server parameter `azure.extensions`.
- **AWS RDS / Aurora PostgreSQL:** pgvector is available by default. The database user needs permission to create extensions.

Load the documents once per environment, and again whenever `knowledge/` changes. Run it as a one-off job with the
same image and secrets:

```bash
docker run --rm -e DATABASE_URL=... sahaj python -m rag.ingest
```

## Azure: Container Apps (recommended)

Container Apps supports WebSockets with no extra setup and gives you HTTPS on a `*.azurecontainerapps.io` domain.

```bash
az group create -n sahaj-rg -l centralindia
az acr create -g sahaj-rg -n sahajacr --sku Basic
az acr login -n sahajacr
docker buildx build --platform linux/amd64 -t sahajacr.azurecr.io/sahaj:1 --push .

az containerapp env create -g sahaj-rg -n sahaj-env -l centralindia
az containerapp create -g sahaj-rg -n sahaj --environment sahaj-env \
  --image sahajacr.azurecr.io/sahaj:1 --registry-server sahajacr.azurecr.io \
  --target-port 8000 --ingress external --transport auto \
  --cpu 2 --memory 4Gi --min-replicas 1 --max-replicas 1 \
  --secrets sarvam-key=<key> db-url=<url> admin-key=<key> \
  --env-vars SARVAM_API_KEY=secretref:sarvam-key DATABASE_URL=secretref:db-url ADMIN_API_KEY=secretref:admin-key
```

Then add an Azure Files volume mounted at `/data` (in the portal under Volumes, or with `az containerapp update --yaml`),
and set a startup probe on `/health`. Keep `--min-replicas 1`: scaling to zero would mean a cold model load during the demo.

## AWS: ECS Fargate behind an Application Load Balancer

Don't use App Runner: it does not support WebSockets.

- **Task:** 2 vCPU / 4 GB (the e5-large model needs about 2.5 GB of RAM), port 8000, secrets from Secrets Manager, and an EFS volume mounted at `/data`.
- **ALB:** HTTPS listener with an ACM certificate forwarding to the target group (HTTP, port 8000). Health check path `/health`, health check grace period 120 s.
- **Idle timeout:** the ALB default is 60 s. The container pings sockets every 20 s, so the default is fine. Raise it to 300 s if you put another proxy in front.
- **Stickiness** is not needed, because each WebSocket stays on the task that accepted it.
- **Region:** `ap-south-1` (Mumbai), with RDS PostgreSQL in the same VPC.

## Scaling: run one replica for now

Each conversation lives in memory on the instance holding its socket, which is fine with more replicas. But the
**audit ledger is a SQLite file**: with more than one replica, each would write its own ledger and they would
disagree (and SQLite on network storage must not be shared by several writers). Keep **exactly one replica**
until the ledger moves to Postgres (already planned in `docs/voice-api.md`).

## After deploying: checklist

1. `https://<host>/health` returns `{"status":"ok"}`.
2. Open `https://<host>/` on an iPhone: consent appears, hold to talk works, and the reply is spoken.
3. `https://<host>/audit/verify` with `X-Admin-Key` returns `intact: true`.
4. Redeploy and confirm the installed PWA picks up the new version on its next launch (the service worker auto-updates; `sw.js` and `index.html` are served `no-cache`).
