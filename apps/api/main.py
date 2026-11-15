from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from auth import store as auth_store
from rag import store
from rag.embeddings import warm_up
from orchestrator import registry
from routers import audit, auth, chat, stt, users, voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.open_pool()  # knowledge base (Postgres + pgvector)
    await auth_store.init_schema()  # users, refresh tokens, per-user memory (same database)
    await warm_up()          # load the embedding model now, not on the first question
    yield
    await registry.shutdown()
    await store.close_pool()


app = FastAPI(title="Sahaj", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(stt.router)
app.include_router(voice.router)
app.include_router(audit.router)


@app.exception_handler(auth_store.Unavailable)
async def unavailable(_: Request, e: auth_store.Unavailable):
    return JSONResponse({"detail": str(e)}, status_code=503)


@app.get("/health")
async def health():
    return {"status": "ok"}
