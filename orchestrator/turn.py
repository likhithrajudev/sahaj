from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Turn:
    """What the assistant wants to say. The session checks it with the guardrails before anyone sees it."""
    text: str
    kind: str = "answer"                 # answer | ask | confirm | recommendation | compare
    agent: str = "insurance"
    sources: Dict[str, str] = field(default_factory=dict)   # what the text may cite
    allow_recommendation: bool = False   # True only for text built from the recommendation engine's facts
    judge: bool = True                   # also run the model fact-check (needs sources)
    detailed: bool = False               # the fact-check need not insist every fact is on point
    asked: str = ""                      # what the fact-check judges the text against
    card: Optional[dict] = None          # structured data for the UI (a recommendation or a comparison table)
    fallback: Optional[str] = None       # said instead if the text is blocked
    append: List[str] = field(default_factory=list)  # fixed text added after the checks (for example disclosures)
    on_blocked: Optional[Callable[[], None]] = None  # called if the text is blocked (to undo flow state)
    sensitive_input: bool = False   # the person's message contained personal details: keep it out of records
    prechecked: bool = False         # the producer already ran the guardrails on this exact text and it passed
    handoff_after: bool = False      # after saying this, bring in a person
    request_consent: Optional[str] = None  # ask the person for this consent before anything else
    cache_key: Optional[tuple] = None      # store this reply in the verified-answer cache if it passes the checks
    from_cache: bool = False               # served from the verified-answer cache (already checked when stored)
