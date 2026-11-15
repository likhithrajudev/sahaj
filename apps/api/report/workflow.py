"""The workflow report: what the orchestrator did in a conversation, and how well it did it.

Built only from the audit trail, which never holds a person's personal answers (those turns are recorded as
withheld), so the report cannot reveal them either. `include_text=False` also drops the remaining transcripts and
replies, leaving only metrics.
"""
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

import config
from trust import ledger


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))], 1)


def _stats(values: List[float]) -> dict:
    return {"n": len(values), "mean_ms": round(sum(values) / len(values), 1) if values else None,
            "p50_ms": _pct(values, 50), "p95_ms": _pct(values, 95), "max_ms": round(max(values), 1) if values else None}


def _turn(entry: dict, index: int, include_text: bool) -> dict:
    steps = entry["payload"]["steps"]
    of = lambda name: [s for s in steps if s["step"] == name]
    first = lambda name: next(iter(of(name)), None)
    stt, intent, route, guard, retr = first("stt"), first("intent"), first("route"), first("guardrail"), first("retrieval")
    llm = of("llm")
    clauses = (retr or {}).get("clauses", [])
    turn = {
        "index": index, "trace_id": entry["trace_id"], "at": entry["created_at"],
        "language": (stt or {}).get("language"),
        "intent": (intent or {}).get("intent"), "confidence": (intent or {}).get("confidence"),
        "detail": (intent or {}).get("detail"), "intent_reason": (intent or {}).get("reason"),
        "intent_source": (intent or {}).get("source"),
        "path": (route or {}).get("path", []),
        "decision_ms": round((max(s["t"] for s in steps) - min(s["t"] for s in steps)) * 1000, 1) if steps else 0,
        "nodes": [{"name": s["name"], "ms": s["ms"]} for s in of("node")],
        "llm_calls": [{k: s[k] for k in ("purpose", "ms", "input_tokens", "output_tokens", "cached_tokens", "app_cache_hit")}
                      for s in llm],
        "caches": [{"layer": s["layer"], "hit": s["hit"]} for s in of("cache")],
        "retrieval": {"clauses": len(clauses), "top_similarity": round(max((c["similarity"] for c in clauses), default=0), 3) or None,
                      "scoped_to": (retr or {}).get("scoped_to"), "keys": [c["key"] for c in clauses]} if retr else None,
        "verdict": (guard or {}).get("verdict"), "kind": (guard or {}).get("kind"), "from_cache": (guard or {}).get("from_cache", False),
        "handoff": next(({"reason": s["reason"], "reference": s["reference"]} for s in of("handoff")), None),
        "recommendation": next(({"plans": s["plans"], "rules_version": s["rules_version"]} for s in of("recommendation")), None),
        "error": next((s["message"] for s in of("error")), None),
        "details_withheld": bool(stt and "withheld" in str(stt.get("transcript", ""))),
    }
    if include_text:
        turn["transcript"] = (stt or {}).get("transcript")
        turn["reply"] = (guard or {}).get("reply")
    return turn


def build(subject: str, include_text: bool = True) -> dict:
    entries = ledger.entries(subject=subject)
    audits = [e for e in entries if e["kind"] == "audit"]
    turns = [_turn(e, i + 1, include_text) for i, e in enumerate(audits)]
    return _summarise(subject, turns, entries)


def _summarise(subject: str, turns: List[dict], entries: List[dict]) -> dict:
    from orchestrator.graph import GRAPH  # imported here: the graph imports the whole app

    classified = [t for t in turns if t["intent"]]
    node_ms, purpose = defaultdict(list), defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cached": 0, "app_cache_hits": 0, "ms": []})
    caches = defaultdict(lambda: {"hits": 0, "misses": 0})
    for t in turns:
        for n in t["nodes"]:
            node_ms[n["name"]].append(n["ms"])
        for call in t["llm_calls"]:
            p = purpose[call["purpose"]]
            p["calls"] += 1
            p["input"] += call["input_tokens"]; p["output"] += call["output_tokens"]; p["cached"] += call["cached_tokens"]
            p["app_cache_hits"] += call["app_cache_hit"]; p["ms"].append(call["ms"])
        for c in t["caches"]:
            caches[c["layer"]]["hits" if c["hit"] else "misses"] += 1

    calls = [c for t in turns for c in t["llm_calls"]]
    total_in, total_out = sum(c["input_tokens"] for c in calls), sum(c["output_tokens"] for c in calls)
    total_cached = sum(c["cached_tokens"] for c in calls)
    verdicts = Counter(t["verdict"] for t in turns if t["verdict"])
    answered = sum(verdicts.values())
    times = [e["created_at"] for e in entries]
    consents = [{"purpose": e["payload"]["purpose"], "event": e["payload"]["event"], "at": e["created_at"]}
                for e in entries if e["kind"] == "consent"]
    retrieved = [t["retrieval"] for t in turns if t["retrieval"]]

    report = {
        "session": subject, "generated_at": time.time(),
        "overview": {
            "turns": len(turns), "started": min(times) if times else None, "ended": max(times) if times else None,
            "duration_s": round(max(times) - min(times), 1) if times else 0,
            "languages": dict(Counter(t["language"] for t in turns if t["language"])),
            "errors": [t["error"] for t in turns if t["error"]],
            "handoffs": [t["handoff"] for t in turns if t["handoff"]],
            "turns_with_personal_details_withheld": sum(t["details_withheld"] for t in turns),
        },
        "consents": consents,
        "intents": {
            "distribution": dict(Counter(t["intent"] for t in classified)),
            "mean_confidence": round(sum(t["confidence"] for t in classified) / len(classified), 3) if classified else None,
            "decided_by_context": sum(t["intent_source"] == "context" for t in classified),
            "decided_by_classifier": sum(t["intent_source"] == "classifier" for t in classified),
            "low_confidence_turns": sum(1 for t in classified if t["intent_source"] == "classifier" and t["confidence"] < config.INTENT_MIN_CONFIDENCE),
            "deep_requests": sum(t["detail"] == "deep" for t in classified),
        },
        "routing": {"paths": dict(Counter(" > ".join(t["path"]) for t in turns if t["path"])),
                    "graph_mermaid": GRAPH.get_graph().draw_mermaid()},
        "latency": {"decision_ms": _stats([t["decision_ms"] for t in turns]),
                    "by_node": {k: _stats(v) for k, v in sorted(node_ms.items())},
                    "note": "Decision time: from the transcript arriving to the verified reply. Speech recognition and speech synthesis are not included."},
        "llm": {
            "calls": len(calls), "input_tokens": total_in, "output_tokens": total_out,
            "provider_cached_tokens": total_cached,
            "provider_cache_hit_rate": round(total_cached / total_in, 3) if total_in else None,
            "calls_avoided_by_app_cache": sum(c["app_cache_hit"] for c in calls),
            "by_purpose": {k: {"calls": v["calls"], "input_tokens": v["input"], "output_tokens": v["output"],
                               "cached_tokens": v["cached"], "app_cache_hits": v["app_cache_hits"], **_stats(v["ms"])}
                           for k, v in sorted(purpose.items())},
        },
        "caches": {k: {**v, "hit_rate": round(v["hits"] / (v["hits"] + v["misses"]), 3) if v["hits"] + v["misses"] else None}
                   for k, v in sorted(caches.items())},
        "quality": {"replies_checked": answered, "passed": verdicts.get("pass", 0),
                    "blocked": answered - verdicts.get("pass", 0), "block_reasons": {k: v for k, v in verdicts.items() if k != "pass"},
                    "fallback_rate": round((answered - verdicts.get("pass", 0)) / answered, 3) if answered else None,
                    "served_from_verified_cache": sum(t["from_cache"] for t in turns)},
        "retrieval": {"turns": len(retrieved),
                      "mean_clauses": round(sum(r["clauses"] for r in retrieved) / len(retrieved), 2) if retrieved else None,
                      "mean_top_similarity": round(sum(r["top_similarity"] or 0 for r in retrieved) / len(retrieved), 3) if retrieved else None,
                      "turns_with_no_clause_found": sum(1 for r in retrieved if not r["clauses"])},
        "recommendations": [{"at": e["created_at"], "rules_version": e["payload"].get("rules_version"),
                             "catalogue_is_sample": e["payload"].get("catalogue_is_sample"),
                             "profile_bands": e["payload"].get("profile_bands"),
                             "ranked": [{"product": r["product_id"], "rank": r["rank"], "score": r["score"]} for r in e["payload"].get("ranked", [])]}
                            for e in entries if e["kind"] == "recommendation"],
        "turns": turns,
    }
    if config.PRICE_INPUT_PER_M is not None and config.PRICE_OUTPUT_PER_M is not None:
        cached_price = config.PRICE_CACHED_PER_M if config.PRICE_CACHED_PER_M is not None else config.PRICE_INPUT_PER_M
        fresh = total_in - total_cached
        report["llm"]["estimated_cost"] = {
            "amount": round((fresh * config.PRICE_INPUT_PER_M + total_cached * cached_price + total_out * config.PRICE_OUTPUT_PER_M) / 1e6, 4),
            "without_prompt_cache": round((total_in * config.PRICE_INPUT_PER_M + total_out * config.PRICE_OUTPUT_PER_M) / 1e6, 4),
            "basis": "rupees per million tokens, from PRICE_* settings"}
    return report


def build_overview(limit: int = 50) -> dict:
    """The same measures across the most recent sessions, without any per-turn detail."""
    subjects = ledger.subjects("audit", limit)
    reports = [build(s, include_text=False) for s in subjects]
    turns = [t for r in reports for t in r["turns"]]
    shell = _summarise("all", turns, [e for s in subjects for e in ledger.entries(subject=s)])
    shell["overview"]["sessions"] = len(subjects)
    shell["turns"] = []
    shell["recommendations"] = [{"at": r["at"], "ranked": r["ranked"], "profile_bands": r["profile_bands"]}
                                for rep in reports for r in rep["recommendations"]]
    return shell
