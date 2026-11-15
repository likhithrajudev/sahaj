"""Retrieval accuracy check against the real database and embedding model.

    python tests/eval_retrieval.py

Re-run after changing documents, the embedding model or RETRIEVAL_MIN_SIMILARITY. Add your own
questions (in the languages your users speak) with the clause that should answer each.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from rag import store
from rag.embeddings import embed_queries

# (question, domain, pattern of the clause keys that validly answer it). With many plans loaded, several
# documents can answer the same question, so a case accepts any matching key.
H = "health-[a-z-]+"
C = "concepts-insurance-basics"
CASES = [
    ("What is the waiting period for pre-existing diseases?", "insurance", rf"({H}:2\.2|{C}:3\.1)"),
    ("How much is the sum insured?", "insurance", rf"({H}:1\.1|[a-z-]+:1\.1|{C}:5\.1)"),
    ("Is dental treatment covered?", "insurance", rf"({H}:3\.1|{C}:3\.2)"),
    ("How soon must I tell the insurer about a hospital admission?", "insurance", rf"({H}:4\.1|{C}:4\.1)"),
    ("Can I cancel the policy after buying it?", "insurance", r"[a-z-]+:5\.[12]"),
    ("What is the processing fee?", "loan", r"sample-kfs:2\.1"),
    ("Can I repay early without a charge?", "loan", r"sample-kfs:3\.1"),
    ("What is the interest rate?", "loan", r"sample-kfs:1\.2"),
    ("Who do I complain to?", "loan", r"sample-kfs:5\.1"),
    ("What happens if I miss an EMI?", "loan", r"sample-kfs:2\.2"),
    ("पहले से मौजूद बीमारियों के लिए प्रतीक्षा अवधि कितनी है?", "insurance", rf"({H}:2\.2|{C}:3\.1)"),
    ("क्या मैं लोन समय से पहले चुका सकता हूँ?", "loan", r"sample-kfs:3\.1"),
    ("प्रोसेसिंग फीस कितनी लगेगी?", "loan", r"sample-kfs:2\.1"),
    ("शिकायत कहाँ करूँ?", "loan", r"sample-kfs:5\.1"),
    ("கடனுக்கான வட்டி விகிதம் என்ன?", "loan", r"sample-kfs:1\.2"),
    ("పాలసీ రద్దు చేసుకోవచ్చా?", "insurance", r"[a-z-]+:5\.[12]"),
    ("ক্লেম করার জন্য কত সময়ের মধ্যে জানাতে হবে?", "insurance", rf"({H}:4\.[12]|{C}:4\.[12])"),
    ("विमा रक्कम किती आहे?", "insurance", rf"([a-z-]+:1\.1|{C}:5\.1)"),
    ("loan ka processing fee kitna hai?", "loan", r"sample-kfs:2\.1"),
    ("claim kab tak intimate karna hota hai?", "insurance", rf"({H}:4\.[12]|{C}:4\.[12])"),
    # the advisory use cases
    ("What is the difference between term insurance and whole life insurance?", "insurance", rf"{C}:1\.[123]"),
    ("टर्म इंश्योरेंस और होल लाइफ में क्या अंतर है?", "insurance", rf"{C}:1\.[123]"),
    ("What does claim settlement ratio mean?", "insurance", rf"{C}:4\.3"),
    ("How much life cover do I need?", "insurance", rf"{C}:5\.1"),
    ("What is cashless treatment?", "insurance", rf"({C}:4\.1|{H}:4\.1)"),
]
# Unrelated to the documents: retrieval itself must reject these.
UNRELATED = [
    ("Who won the cricket world cup?", "insurance"),
    ("What is the capital of France?", "loan"),
]
# Related to the topic but not answered by the documents. Cosine similarity cannot tell, so these pass
# retrieval by design and must be refused later by the answer checks. Listed so you can watch the scores.
UNANSWERABLE = [
    ("What is the cashback on this policy?", "insurance"),
    ("Does the policy cover maternity?", "insurance"),
    ("What is the foreclosure charge?", "loan"),
]
OFF_TOPIC = UNRELATED + UNANSWERABLE


async def main() -> None:
    await store.open_pool()
    questions = [q for q, *_ in CASES] + [q for q, _ in OFF_TOPIC]
    vectors = await embed_queries(questions)
    top1 = top3 = kept = 0
    for (question, domain, want), vector in zip(CASES, vectors):
        hits = await store.search(domain, vector, 3)
        keys = [h["key"] for h in hits]
        right = lambda key: re.fullmatch(want, key) is not None
        top1 += right(keys[0])
        top3 += any(right(k) for k in keys)
        found = next((h for h in hits if right(h["key"])), None)
        kept += bool(found and found["similarity"] >= config.RETRIEVAL_MIN_SIMILARITY)
        if not right(keys[0]):
            print(f"  miss: {question[:44]!r} -> {keys[0]} ({hits[0]['similarity']:.2f}), wanted {want}")
    n = len(CASES)
    print(f"{config.EMBED_MODEL}: top-1 {top1}/{n}   top-3 {top3}/{n}   "
          f"correct clause above threshold {config.RETRIEVAL_MIN_SIMILARITY}: {kept}/{n}")

    best = [(await store.search(d, v, 1))[0]["similarity"] for (_, d), v in zip(OFF_TOPIC, vectors[n:])]
    unrelated, unanswerable = best[:len(UNRELATED)], best[len(UNRELATED):]
    rejected = all(s < config.RETRIEVAL_MIN_SIMILARITY for s in unrelated)
    print(f"unrelated questions, best similarity {[round(s, 2) for s in unrelated]}: "
          + ("all rejected" if rejected else "SOME ACCEPTED, raise RETRIEVAL_MIN_SIMILARITY"))
    print(f"related but unanswerable, best similarity {[round(s, 2) for s in unanswerable]}: "
          "pass retrieval by design; the answer checks must refuse them")
    await store.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
