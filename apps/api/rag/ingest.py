"""Load knowledge/<domain>/*.md into pgvector.   Run:  python -m rag.ingest

Only new or changed clauses are embedded. Clauses removed from the files are deleted.
"""
import asyncio

import config
from rag import loader, store
from rag.embeddings import embed_passages

LONG_CLAUSE = 1800  # characters; the embedding model reads about 512 tokens and truncates the rest


async def sync_all() -> dict:
    """Bring the database in line with knowledge/: embed new or changed clauses, delete removed ones. The pool must be
    open. Returns {domain: clauses}. Runs as the platform: these documents are shared by every tenant."""
    import tenancy
    with tenancy.system():
        return await _sync_all()


async def _sync_all() -> dict:
    summary = {}
    for domain in loader.domains():
        chunks = loader.load_chunks(domain)
        have = await store.existing(domain)
        todo = [c for c in chunks
                if have.get(f"{c['doc_id']}:{c['clause']}") != {"sha256": c["sha256"], "model": config.EMBED_MODEL}]

        for c in todo:
            if len(c["content"]) > LONG_CLAUSE:
                print(f"  warning: {c['doc_id']}:{c['clause']} is long and will be truncated when embedded; split it")
        vectors = await embed_passages([c["content"] for c in todo]) if todo else []
        for c, v in zip(todo, vectors):
            c["embedding"] = v

        keep = [f"{c['doc_id']}:{c['clause']}" for c in chunks]
        await store.sync(domain, todo, keep)
        print(f"{domain}: {len(chunks)} clauses ({len(todo)} embedded, {len(have) - len(set(have) & set(keep))} removed)")
        summary[domain] = len(chunks)
    return summary


async def main() -> None:
    await store.open_pool()
    try:
        await sync_all()
    finally:
        await store.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
