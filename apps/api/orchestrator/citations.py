"""Turn a cited source into what the UI shows: the document's name, the clause number and title, and the text.

Source keys are `<doc>:<clause>` for document clauses (`health-lotus-care:3.2`) and `<kind>:<name>` for facts the
code computed (`calc:emi`, `rec:cover`, `profile:summary`, `health-lotus-care:compare`).
"""
import re
from typing import Optional

from advisory import catalogue

FIXED_DOCS = {
    "concepts-insurance-basics": "Insurance basics",
    "concepts-loan-basics": "Loan basics",
    "sample-kfs": "Loan Key Facts Statement (SAMPLE)",
    "calc": "Loan calculation",
    "rec": "Recommendation engine",
    "profile": "Your details",
}
CLAUSE = re.compile(r"(\d+(?:\.\d+)*)\s+([^\n]+)\n?(.*)", re.S)


def doc_name(doc_id: str) -> str:
    if doc_id in FIXED_DOCS:
        return FIXED_DOCS[doc_id]
    try:
        return catalogue.by_id(doc_id)["name"]
    except StopIteration:
        return doc_id.replace("-", " ").capitalize()


def describe(key: str, text: str) -> dict:
    """{id, text, doc, clause, title, body}. clause/title are None for computed facts."""
    doc_id, _, ref = key.partition(":")
    clause: Optional[str] = None
    title: Optional[str] = None
    body = text
    m = CLAUSE.match(text.strip())
    if m and m.group(1) == ref:  # a document clause: "3.2 Pre-existing diseases\n<body>"
        clause, title, body = m.group(1), m.group(2).strip().rstrip("."), m.group(3).strip()
    return {"id": key, "text": text, "doc": doc_name(doc_id), "clause": clause, "title": title, "body": body}
