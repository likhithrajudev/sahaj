import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(".env.local")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_CHAT_MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b-conversations")

# Knowledge base: Postgres + pgvector, cosine similarity over OpenAI embeddings (multilingual, so a Hindi question finds
# an English clause). Changing the model or the dimension rebuilds the knowledge base on the next start.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/sahaj")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))
OPENAI_EMBED_PRICE_PER_M = float(os.getenv("OPENAI_EMBED_PRICE_PER_M", "0.02"))   # USD per million tokens (estimate)
# Load knowledge/ into the database when the API starts (only new or changed clauses are embedded). Turn off to ingest by hand.
AUTO_INGEST = os.getenv("AUTO_INGEST", "true").lower() in ("1", "true", "yes")
RETRIEVAL_TOP_K = 4
RETRIEVAL_TOP_K_DEEP = 8
# Cosine similarity below which a clause is not used. It only removes clearly unrelated text; "related but not
# answerable" is caught by the answer checks. Re-measure with tests/eval_retrieval.py whenever the model or documents change.
RETRIEVAL_MIN_SIMILARITY = float(os.getenv("RETRIEVAL_MIN_SIMILARITY", "0.30"))

# Prompt caching. Sarvam's provider-side prefix cache only hits when calls carry the same x-session-affinity key,
# so one key per conversation is sent. The in-memory caches below never touch disk and skip anything personal.
SARVAM_AFFINITY = os.getenv("SARVAM_AFFINITY", "true").lower() in ("1", "true", "yes")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "512"))
APP_CACHE_ENABLED = os.getenv("APP_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")

# Below this confidence the orchestrator asks a clarifying question instead of guessing the intent.
INTENT_MIN_CONFIDENCE = float(os.getenv("INTENT_MIN_CONFIDENCE", "0.6"))

# Optional prices (rupees per million tokens) so the workflow report can estimate cost. Leave unset to omit it.
PRICE_INPUT_PER_M = float(os.getenv("PRICE_INPUT_PER_M")) if os.getenv("PRICE_INPUT_PER_M") else None
PRICE_OUTPUT_PER_M = float(os.getenv("PRICE_OUTPUT_PER_M")) if os.getenv("PRICE_OUTPUT_PER_M") else None
PRICE_CACHED_PER_M = float(os.getenv("PRICE_CACHED_PER_M")) if os.getenv("PRICE_CACHED_PER_M") else None

# Kill switch for policy recommendations. Off = Sahaj still explains and compares, but never recommends.
ADVISORY_ENABLED = os.getenv("ADVISORY_ENABLED", "true").lower() in ("1", "true", "yes")

LEDGER_DB = os.getenv("LEDGER_DB", "ledger.db")           # consent + audit + handoff records
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")                # protects /audit; endpoint is disabled if unset
HANDOFF_WEBHOOK_URL = os.getenv("HANDOFF_WEBHOOK_URL")    # where human-handoff packets are delivered

# Deployment. WEB_DIST is the built web app (apps/web/dist) that FastAPI serves at /, so the app, the API and
# /ws/voice share one origin (no CORS needed, and wss:// just works behind the load balancer).
WEB_DIST = os.getenv("WEB_DIST", str(Path(__file__).resolve().parent.parent / "web" / "dist"))

# ---- Accounts: Google sign-in exchanged for Sahaj's own JWTs. Auth is disabled (503) until these are set.
JWT_SECRET = os.getenv("JWT_SECRET")                      # signs access tokens; at least 32 random characters
JWT_ISSUER = os.getenv("JWT_ISSUER", "sahaj")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))
# OAuth client ids a Google ID token may be issued for (one per platform: web, Android, iOS), comma separated.
GOOGLE_CLIENT_IDS = [c.strip() for c in os.getenv("GOOGLE_CLIENT_IDS", "").split(",") if c.strip()]
# Emails that become admins when they sign in. Everyone else is a plain user until an admin changes it.
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
CORS_ORIGINS = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]

# ---- Per-user memory (only with the person's "memory" consent)
MEMORY_MAX_SUMMARIES = int(os.getenv("MEMORY_MAX_SUMMARIES", "10"))      # older conversation summaries are dropped
MEMORY_PROMPT_SUMMARIES = int(os.getenv("MEMORY_PROMPT_SUMMARIES", "3")) # how many recent ones reach the model

# ---- Observability
# LangSmith traces each turn (graph nodes, model calls, tokens, latency). Off unless enabled AND a key is set.
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() in ("1", "true", "yes")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "sahaj")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT")      # only for EU or self-hosted LangSmith
# Traces leave your infrastructure, so by default LangSmith gets the shape of a turn (steps, timings, token counts)
# but not the text of prompts and replies. Set to false only once you have a data-processing agreement in place.
LANGSMITH_HIDE_IO = os.getenv("LANGSMITH_HIDE_IO", "true").lower() in ("1", "true", "yes")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")     # tags traces and logs: development | staging | production
METRICS_TOKEN = os.getenv("METRICS_TOKEN")                # when set, /metrics needs "Authorization: Bearer <token>"
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")              # "json" for log shipping

# ---- API gateway layer (gateway/)
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes")
RATE_LIMIT_AUTH_PER_MIN = int(os.getenv("RATE_LIMIT_AUTH_PER_MIN", "20"))        # /auth/*: sign-in and refresh
RATE_LIMIT_CHAT_PER_MIN = int(os.getenv("RATE_LIMIT_CHAT_PER_MIN", "60"))        # /chat/*, /stt: they call the model
RATE_LIMIT_WS_PER_MIN = int(os.getenv("RATE_LIMIT_WS_PER_MIN", "30"))            # new voice connections
RATE_LIMIT_DEFAULT_PER_MIN = int(os.getenv("RATE_LIMIT_DEFAULT_PER_MIN", "300"))
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(30 * 1024 * 1024)))         # largest accepted request body
# Behind a proxy or load balancer the client address is in X-Forwarded-For. Trust it only when one is really in front.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")

# ---- File storage (Amazon S3). Uploads are disabled (503) until AWS_S3_BUCKET is set.
# Credentials are NOT settings here: boto3 finds them itself (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, AWS_PROFILE or SSO,
# or the IAM role of the server). Prefer a role in production.
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-2"
AWS_PROFILE = os.getenv("AWS_PROFILE")
# Optional explicit keys (an IAM user). Without them boto3 uses its normal chain; a server should use an IAM role instead.
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")   # only for an S3-compatible store such as MinIO in local development
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))     # keep below MAX_BODY_BYTES
MAX_FILES_PER_USER = int(os.getenv("MAX_FILES_PER_USER", "50"))

# ---- Local testing
# A sign-in that needs no Google account, for the test page. Works only when ENVIRONMENT=development AND the caller is
# on this machine, so a deployed instance cannot be signed into this way even if the flag is left on.
DEV_LOGIN = os.getenv("DEV_LOGIN", "false").lower() in ("1", "true", "yes")
# Serve the test console at /test (development only).
TEST_PAGE = os.getenv("TEST_PAGE", "true").lower() in ("1", "true", "yes")

# ---- Asking questions about a person's own documents (PDFs)
DOC_MAX_PAGES = int(os.getenv("DOC_MAX_PAGES", "60"))
DOC_MAX_CHUNKS = int(os.getenv("DOC_MAX_CHUNKS", "200"))
DOC_CHUNK_CHARS = int(os.getenv("DOC_CHUNK_CHARS", "900"))

# ---- Which model answers. Voice conversations stay on Sarvam end to end (speech-to-text, answer, text-to-speech). Typed
# conversations use OpenAI when OPENAI_API_KEY is set, otherwise Sarvam. Embeddings are always OpenAI's.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
TEXT_LLM_PROVIDER = os.getenv("TEXT_LLM_PROVIDER", "openai")       # openai | sarvam
VOICE_LLM_PROVIDER = os.getenv("VOICE_LLM_PROVIDER", "sarvam")     # openai | sarvam

# ---- What things cost, in US dollars. ESTIMATES: providers change prices, so check them against your invoices and
# override here. OPENAI_* are per million tokens (input, input served from the provider's prompt cache, output).
OPENAI_PRICE_IN_PER_M = float(os.getenv("OPENAI_PRICE_IN_PER_M", "0.15"))
OPENAI_PRICE_CACHED_PER_M = float(os.getenv("OPENAI_PRICE_CACHED_PER_M", "0.075"))
OPENAI_PRICE_OUT_PER_M = float(os.getenv("OPENAI_PRICE_OUT_PER_M", "0.60"))
SARVAM_LLM_PRICE_IN_PER_M = float(os.getenv("SARVAM_LLM_PRICE_IN_PER_M", "0.25"))
SARVAM_LLM_PRICE_CACHED_PER_M = float(os.getenv("SARVAM_LLM_PRICE_CACHED_PER_M", "0.125"))
SARVAM_LLM_PRICE_OUT_PER_M = float(os.getenv("SARVAM_LLM_PRICE_OUT_PER_M", "0.75"))
SARVAM_STT_PRICE_PER_HOUR = float(os.getenv("SARVAM_STT_PRICE_PER_HOUR", "0.35"))          # of audio
SARVAM_TTS_PRICE_PER_10K_CHARS = float(os.getenv("SARVAM_TTS_PRICE_PER_10K_CHARS", "0.18"))
# Sarvam bills speech-to-text by audio length, which we do not get back, so it is estimated from the size of the
# recording (browser recordings are Opus at roughly 32 kbit/s).
STT_BYTES_PER_SECOND = int(os.getenv("STT_BYTES_PER_SECOND", "4000"))

# ---- Spending limit per person. Counted from the ledger of every model, speech-to-text and text-to-speech call.
BUDGET_ENABLED = os.getenv("BUDGET_ENABLED", "true").lower() in ("1", "true", "yes")
USER_BUDGET_USD = float(os.getenv("USER_BUDGET_USD", "5"))   # per person per calendar month (UTC); an admin can override it per person
BUDGET_WARN_AT = float(os.getenv("BUDGET_WARN_AT", "0.8"))   # tell the person when this share is used

# ---- The customer executive desk (human in the loop)
# How soon an executive should pick a case up, by priority. Past this a case shows as overdue.
DESK_SLA_MINUTES = {"urgent": int(os.getenv("DESK_SLA_URGENT_MINUTES", "5")),
                    "high": int(os.getenv("DESK_SLA_HIGH_MINUTES", "30")),
                    "normal": int(os.getenv("DESK_SLA_NORMAL_MINUTES", "120"))}
LOW_CONFIDENCE_HANDOFF_AFTER = int(os.getenv("LOW_CONFIDENCE_HANDOFF_AFTER", "2"))   # clarifying questions in a row
