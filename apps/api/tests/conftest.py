import os
import sys
from pathlib import Path

# Tests never send traces to LangSmith (or anywhere else outside this machine), whatever .env.local says. This must be set
# before `config` is imported: loading .env.local does not override variables that are already set.
for _name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
    os.environ[_name] = "false"

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


@pytest.fixture(autouse=True)
def default_tenant():
    """Tests act as a person of the default tenant unless they say otherwise (asyncio.run copies this context)."""
    import tenancy
    token = tenancy.current_tenant.set(config.DEFAULT_TENANT)
    yield
    tenancy.current_tenant.reset(token)


@pytest.fixture(autouse=True)
def no_real_providers(monkeypatch):
    """No test reaches OpenAI or Sarvam with the real keys in .env.local: tests that need a provider mock it."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "SARVAM_API_KEY", None)


@pytest.fixture(autouse=True)
def no_rate_limit_by_default(monkeypatch):
    """Rate-limit state is shared by the whole process, so tests that sign in repeatedly would trip it. The tests that
    are about rate limiting (test_observability.py) switch it back on."""
    from gateway.limiter import LIMITER
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    LIMITER.reset()
