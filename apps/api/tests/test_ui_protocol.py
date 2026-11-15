"""Fields the web app relies on: citation details and needs-analysis progress."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advisory.profile import Profile
from orchestrator.citations import describe


def test_document_clause_is_split_into_title_and_body():
    c = describe("health-lotus-care:3.2", "3.2 Pre-existing diseases\nCovered after 36 months.")
    assert c["doc"] == "Lotus Care (SAMPLE)"
    assert (c["clause"], c["title"], c["body"]) == ("3.2", "Pre-existing diseases", "Covered after 36 months.")
    assert c["text"] == "3.2 Pre-existing diseases\nCovered after 36 months."  # unchanged for older clients


def test_computed_fact_has_no_clause():
    c = describe("calc:emi", "For a loan of Rs 5,00,000 ...")
    assert c["doc"] == "Loan calculation" and c["clause"] is None and c["title"] is None
    assert c["body"] == "For a loan of Rs 5,00,000 ..."


def test_unknown_document_gets_a_readable_name():
    assert describe("some-new-doc:1.1", "1.1 Title\nBody")["doc"] == "Some new doc"


def test_progress_unknown_until_goal_then_counts_answers():
    p = Profile()
    assert p.progress() is None
    p.set("goal", "health")
    answered, total = p.progress()
    assert answered == 1 and total > 3
    p.set("age", 34)
    assert p.progress() == (2, total)
