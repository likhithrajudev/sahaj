import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import tenancy
from rag import loader, store


def test_loader_reads_every_clause():
    chunks = {f"{c['doc_id']}:{c['clause']}": c for c in loader.load_chunks("loan")}
    assert "sample-kfs:2.1" in chunks
    assert chunks["sample-kfs:2.1"]["content"].startswith("2.1 Processing fee")
    assert len(chunks["sample-kfs:2.1"]["sha256"]) == 64


def test_loader_finds_domains():
    assert {"insurance", "loan"} <= set(loader.domains())


def vec(*head):
    return list(head) + [0.0] * (config.EMBED_DIM - len(head))


def run_against_db(scenario):
    async def runner():
        await store.open_pool()
        if store._pool is None:
            pytest.skip("Postgres with pgvector is not reachable at DATABASE_URL")
        try:
            with tenancy.system():
                return await scenario()
        finally:
            await store.close_pool()
    return asyncio.run(runner())


def test_search_ranks_by_cosine_similarity_not_magnitude():
    domain = f"test-{uuid.uuid4().hex[:8]}"
    chunks = [  # deliberately different magnitudes: cosine must ignore them
        {"doc_id": "d", "clause": "A", "content": "A", "sha256": "a", "embedding": vec(10.0)},
        {"doc_id": "d", "clause": "B", "content": "B", "sha256": "b", "embedding": vec(0.0, 0.1)},
        {"doc_id": "d", "clause": "C", "content": "C", "sha256": "c", "embedding": vec(0.1, 0.1)},
    ]

    async def scenario():
        try:
            await store.sync(domain, chunks, [f"d:{c['clause']}" for c in chunks])
            return await store.search(domain, vec(1.0), 3)
        finally:
            await store.sync(domain, [], [])

    hits = run_against_db(scenario)
    assert [h["key"] for h in hits] == ["d:A", "d:C", "d:B"]
    assert hits[0]["similarity"] == pytest.approx(1.0, abs=1e-4)
    assert hits[1]["similarity"] == pytest.approx(0.7071, abs=1e-3)
    assert hits[2]["similarity"] == pytest.approx(0.0, abs=1e-4)


def test_sync_removes_withdrawn_clauses_and_isolates_domains():
    domain, other = f"test-{uuid.uuid4().hex[:8]}", f"test-{uuid.uuid4().hex[:8]}"
    chunk = lambda clause, v: {"doc_id": "d", "clause": clause, "content": clause, "sha256": clause, "embedding": v}

    async def scenario():
        try:
            await store.sync(domain, [chunk("1", vec(1.0)), chunk("2", vec(0.0, 1.0))], ["d:1", "d:2"])
            await store.sync(other, [chunk("9", vec(1.0))], ["d:9"])
            await store.sync(domain, [], ["d:1"])  # clause 2 withdrawn from the source document
            return await store.search(domain, vec(1.0), 5), await store.search(other, vec(1.0), 5)
        finally:
            await store.sync(domain, [], [])
            await store.sync(other, [], [])

    mine, theirs = run_against_db(scenario)
    assert [h["key"] for h in mine] == ["d:1"]    # withdrawn clause is gone
    assert [h["key"] for h in theirs] == ["d:9"]  # other domain untouched
