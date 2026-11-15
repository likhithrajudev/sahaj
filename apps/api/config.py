import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(".env.local")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_CHAT_MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b-conversations")

# Knowledge base: Postgres + pgvector, cosine similarity over multilingual embeddings.
# Embeddings run locally (Sarvam has no embeddings API, and documents never leave your infrastructure).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/sahaj")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-large")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
EMBED_CACHE_DIR = os.getenv("EMBED_CACHE_DIR", ".cache/models")
RETRIEVAL_TOP_K = 4
RETRIEVAL_TOP_K_DEEP = 8
# Cosine similarity below which a clause is not used. e5 scores are compressed (relevant ~0.77-0.90, unrelated
# ~0.70), so this only removes clearly unrelated text; "related but not answerable" is caught by the answer checks.
# Re-measure with tests/eval_retrieval.py whenever the model or documents change.
RETRIEVAL_MIN_SIMILARITY = float(os.getenv("RETRIEVAL_MIN_SIMILARITY", "0.75"))

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

# Deployment. WEB_DIST is the built web app (apps/web/dist) that FastAPI serves at /, so the app, /stt and
# /ws/voice share one origin (no CORS, and wss:// just works behind the load balancer). Set CORS_ORIGINS
# (comma-separated) only if the web app is hosted on a different origin.
WEB_DIST = os.getenv("WEB_DIST", str(Path(__file__).resolve().parent.parent / "web" / "dist"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
