from typing import List, Optional

import config
from rag import store
from rag.embeddings import embed_queries


async def retrieve(domain: str, text: str, history: List[dict], deep: bool = False,
                   doc_ids: Optional[List[str]] = None, user_id: Optional[str] = None) -> List[dict]:
    """Clauses relevant to `text`, best first, each with its cosine similarity.
    `doc_ids` restricts the search to those documents, for questions about a named plan.
    `user_id` also searches that person's own uploaded documents (hits are marked "personal").

    A follow-up like "and for accidents?" means nothing alone, so the previous user question is also
    searched, joined to this one, and each clause keeps its best score across both searches.
    """
    queries = [text]
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if previous:
        queries.append(f"{previous} {text}")

    k = config.RETRIEVAL_TOP_K_DEEP if deep else config.RETRIEVAL_TOP_K
    best = {}
    for vector in await embed_queries(queries):
        found = await store.search(domain, vector, k, doc_ids)
        if user_id:
            from storage import index  # imported here: the knowledge base must work without the accounts side
            found += await index.search(user_id, vector, k)
        for hit in found:
            if hit["similarity"] >= config.RETRIEVAL_MIN_SIMILARITY and hit["similarity"] > best.get(hit["key"], {}).get("similarity", 0):
                best[hit["key"]] = hit
    return sorted(best.values(), key=lambda h: -h["similarity"])[:k]
