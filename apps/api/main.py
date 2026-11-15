from contextlib import asynccontextmanager
from pathlib import Path

import config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
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
if config.CORS_ORIGINS:  # only needed when the web app is served from a different origin than the API
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(stt.router)
app.include_router(voice.router)
app.include_router(audit.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


class SPAStaticFiles(StaticFiles):
    """Serves the built web app; unknown paths fall back to index.html so client-side routes work."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or "." in path.rsplit("/", 1)[-1]:  # missing files stay 404
                raise
            response = await super().get_response("index.html", scope)
        if path in ("sw.js", "index.html", ".", "") or path.endswith(".webmanifest"):
            response.headers["Cache-Control"] = "no-cache"  # so a new deploy reaches installed PWAs
        return response


# Mounted last so they don't shadow the routes. The old test client stays at /test.
app.mount("/test", StaticFiles(directory="static", html=True), name="test")
web_dist = Path(config.WEB_DIST)
if (web_dist / "index.html").is_file():
    app.mount("/", SPAStaticFiles(directory=web_dist, html=True), name="web")
else:  # no web build yet: serve the test client at the root as before
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
