from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from auth import store as auth_store
from gateway.middleware import Gateway
from observability import logs, tracing
import asyncio
import logging

from auth import feedback as feedback_store
from rag import ingest, store
from rag.embeddings import warm_up
from orchestrator import registry
from routers import audit, auth, calculators, chat, consents, desk, feedback, files, financial, inventory, journeys
from routers import marketing as marketing_router
from routers import ops, platform, procedures, search, stt, usage, users, voice
from storage import blob, files as file_store, index as doc_index
from usage import ledger as usage_ledger
from desk import store as desk_store


log = logging.getLogger("sahaj.startup")


async def knowledge_base() -> None:
    """Load the embedding model, then make sure the knowledge base is filled. Failures are logged, not fatal: the
    service still starts, /ready says what is wrong, and questions that need the knowledge base say so."""
    try:
        await warm_up()  # load the embedding model now, not on the first question
    except Exception as e:
        log.error("Embeddings are unavailable (%s). Answers from the knowledge base need them.", e)
        return
    try:
        from rag import embeddings
        await embeddings.init_cache()
        if config.AUTO_INGEST:
            await ingest.sync_all()
        import tenancy
        with tenancy.system():
            have = await store.stats()
        if not have["clauses"]:
            log.error("The knowledge base is empty. Run `python -m rag.ingest`, or set AUTO_INGEST=true.")
        else:
            log.info("Knowledge base ready: %s", have["domains"])
        asyncio.create_task(_reindex())   # PDFs that need reading again (after a model change) are read in the background
    except Exception as e:
        log.error("The knowledge base is not usable (%s). Is Postgres running with pgvector, and DATABASE_URL right?", e)


async def _reindex() -> None:
    try:
        if n := await doc_index.reindex_pending():
            log.info("Re-read %d document(s).", n)
    except Exception as e:
        log.warning("Re-reading documents failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.open_pool()  # knowledge base (Postgres + pgvector)
    await auth_store.init_schema()  # users, refresh tokens, per-user memory (same database)
    try:
        await file_store.init_schema()  # records of uploaded files
        await feedback_store.init_schema()  # ratings of replies
        await doc_index.init_schema()  # passages of uploaded documents
        await usage_ledger.init_schema()  # what each person's calls cost
        await desk_store.init_schema()  # the executive desk: cases and their threads
        from financial import providers as financial_providers, store as financial_store
        await financial_store.init_schema()
        from financial import inventory as financial_inventory
        await financial_inventory.init_schema()
        financial_providers.load_configured()
        from journeys import store as journey_store
        await journey_store.init_schema()
        from memory import episodic, procedural, semantic
        from marketing import store as marketing_store
        await marketing_store.init_schema()
        await episodic.init_schema()    # memory layer 2: past conversations
        await semantic.init_schema()    # memory layer 3: facts with embeddings
        await procedural.init_schema()  # memory layer 4: versioned prompts and workflows
    except auth_store.Unavailable:
        pass
    await knowledge_base()
    yield
    await registry.shutdown()
    await blob.close()
    await store.close_pool()


logs.setup()
tracing.setup()

app = FastAPI(title="Sahaj", lifespan=lifespan)
# Added last = outermost. CORS wraps the gateway so even a 429 or 413 carries CORS headers the browser can read.
app.add_middleware(Gateway)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Request-ID", "Retry-After"])
app.include_router(ops.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(consents.router)
app.include_router(files.router)
app.include_router(feedback.router)
app.include_router(usage.router)
app.include_router(desk.router)
app.include_router(procedures.router)
app.include_router(chat.router)
app.include_router(stt.router)
app.include_router(voice.router)
app.include_router(audit.router)
app.include_router(platform.router)
app.include_router(search.router)
app.include_router(financial.router)
app.include_router(calculators.router)
app.include_router(inventory.router)
app.include_router(marketing_router.router)
app.include_router(journeys.router)


@app.exception_handler(auth_store.Unavailable)
async def unavailable(_: Request, e: auth_store.Unavailable):
    return JSONResponse({"detail": str(e)}, status_code=503)


@app.get("/health")
async def health():
    return {"status": "ok"}


class SinglePageApp(StaticFiles):
    """The console: a client-side route such as /app/documents gets index.html; a missing file (with an extension) stays a 404."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


class SPAStaticFiles(StaticFiles):
    """Serves the built web app (PWA). Unknown app paths fall back to index.html; API paths and missing files stay 404."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            first = path.split("/", 1)[0]
            if e.status_code != 404 or "." in path.rsplit("/", 1)[-1] or first in API_PREFIXES:
                raise
            response = await super().get_response("index.html", scope)
        if path in ("sw.js", "index.html", ".", "") or path.endswith(".webmanifest"):
            response.headers["Cache-Control"] = "no-cache"  # so a new deploy reaches installed PWAs
        return response


# First path segments that belong to the API or the console: never answered with the web app's index.html.
# Keep in sync with API_PATHS in apps/web/vite.config.ts.
API_PREFIXES = {"auth", "users", "admin", "chat", "consents", "files", "feedback", "usage", "desk", "stt", "ws",
                "audit", "drafts", "ready", "metrics", "health", "docs", "redoc", "openapi.json", "test", "app",
                "calculators", "financial", "platform", "search", "inbox"}
web_dist = Path(config.WEB_DIST)
has_web = (web_dist / "index.html").is_file()
console_dist = Path(config.CONSOLE_DIST)
has_console = (console_dist / "index.html").is_file()
test_page = config.TEST_PAGE and config.ENVIRONMENT == "development"

if has_console:  # the console (apps/console/dist): customer pages plus the staff and admin tools
    app.mount("/app", SinglePageApp(directory=console_dist, html=True), name="console")

if test_page:
    # A hand-test console for the whole API: http://127.0.0.1:8000/test/
    app.mount("/test", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="test")

if has_web:  # the PWA (apps/web/dist, or WEB_DIST in the image), mounted last so it never shadows the API
    app.mount("/", SPAStaticFiles(directory=web_dist, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    async def home():
        return RedirectResponse("/app/" if has_console else "/test/" if test_page else "/docs")
