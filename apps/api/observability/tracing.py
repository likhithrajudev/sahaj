"""LangSmith tracing. LangChain and LangGraph report to LangSmith on their own once the LANGSMITH_* environment is set,
so this module does two things: make that environment match config (and switch it firmly off unless asked for), and
describe each turn with tags and metadata so traces can be filtered and matched to Sahaj's own audit trail."""
import hashlib
import logging
import os
from typing import Optional

import config

log = logging.getLogger("sahaj.tracing")


def enabled() -> bool:
    return config.LANGSMITH_TRACING and bool(config.LANGSMITH_API_KEY)


def setup() -> bool:
    """Apply the settings to the environment LangSmith reads. Returns whether tracing is on."""
    if config.LANGSMITH_TRACING and not config.LANGSMITH_API_KEY:
        log.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is not set: tracing stays off.")
    on = enabled()
    flag = "true" if on else "false"
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):  # old names too, so none can switch it on
        os.environ[name] = flag
    if on:
        os.environ["LANGSMITH_API_KEY"] = config.LANGSMITH_API_KEY
        os.environ["LANGSMITH_PROJECT"] = config.LANGSMITH_PROJECT
        hide = "true" if config.LANGSMITH_HIDE_IO else "false"
        os.environ["LANGSMITH_HIDE_INPUTS"] = os.environ["LANGSMITH_HIDE_OUTPUTS"] = hide
        if config.LANGSMITH_ENDPOINT:
            os.environ["LANGSMITH_ENDPOINT"] = config.LANGSMITH_ENDPOINT
        log.info("LangSmith tracing on (project %s, prompts and replies %s).", config.LANGSMITH_PROJECT,
                 "hidden" if config.LANGSMITH_HIDE_IO else "included")
    return on


def person(user_id: str) -> str:
    """A stable reference to a user that LangSmith can group by but that is not their id."""
    salt = (config.JWT_SECRET or "sahaj").encode()
    return hashlib.sha256(salt + user_id.encode()).hexdigest()[:16]


def run_config(*, session_id: str, user_id: str, language: str, channel: str, trace_id: str,
               memory: bool, intent: Optional[str] = None) -> dict:
    """The LangChain run settings for one turn: a name, tags to filter by, and metadata linking the trace to the audit
    trail (`trace_id`). Never the person's id, email or any text."""
    tags = [f"env:{config.ENVIRONMENT}", f"channel:{channel}", f"lang:{language}"]
    if memory:
        tags.append("memory")
    return {"run_name": "sahaj_turn", "tags": tags,
            "metadata": {"session_id": session_id, "user_ref": person(user_id), "audit_trace_id": trace_id,
                         "language": language, "channel": channel, "environment": config.ENVIRONMENT}}
