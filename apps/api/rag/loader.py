"""Reads knowledge/<domain>/*.md. Each `## <clause> <title>` section is one chunk."""
import hashlib
import re
from pathlib import Path
from typing import List

KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge"


def load_chunks(domain: str) -> List[dict]:
    chunks = []
    for path in sorted((KNOWLEDGE / domain).glob("*.md")):
        for block in re.split(r"(?m)^## ", path.read_text())[1:]:
            content = block.strip()
            chunks.append({
                "domain": domain,
                "doc_id": path.stem,
                "clause": content.split()[0],
                "content": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            })
    return chunks


def domains() -> List[str]:
    return sorted(p.name for p in KNOWLEDGE.iterdir() if p.is_dir())


def concept_docs(domain: str) -> List[str]:
    """Documents of general explanations (concepts-*.md), as opposed to the wording of one particular plan."""
    return [p.stem for p in sorted((KNOWLEDGE / domain).glob("concepts-*.md"))]
