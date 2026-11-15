from contextlib import asynccontextmanager

from fastapi import FastAPI
from rag import store
from rag.embeddings import warm_up
from routers import audit, stt, voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.open_pool()  # knowledge base (Postgres + pgvector)
    await warm_up()          # load the embedding model now, not on the first question
    yield
    await store.close_pool()


app = FastAPI(title="Sahaj", lifespan=lifespan)
app.include_router(stt.router)
app.include_router(voice.router)
app.include_router(audit.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
