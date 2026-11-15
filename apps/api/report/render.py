"""Markdown and HTML renderings of a workflow report (the JSON form is the report dict itself)."""
import html
import time
from typing import Any, Dict, List

MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"


def _when(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _dec(x, places: int = 2) -> str:
    return "-" if x is None else f"{x:.{places}f}"


def _num(x) -> str:
    return "-" if x is None else f"{x:,}" if isinstance(x, int) else f"{x:,.1f}"


def sections(r: Dict[str, Any]) -> List[dict]:
    """The report as an ordered list of {title, intro?, table: (headers, rows)?, code?} blocks, shared by both renderers."""
    o, i, lat, llm, q, rt = r["overview"], r["intents"], r["latency"], r["llm"], r["quality"], r["retrieval"]
    out = []
    scope = f"Session `{r['session']}`" if r["session"] != "all" else f"{o.get('sessions', 0)} most recent sessions"
    out.append({"title": "Overview", "intro": f"{scope}. Generated {_when(r['generated_at'])}.", "table": (
        ["Measure", "Value"],
        [["Turns", _num(o["turns"])], ["Started", _when(o["started"])], ["Duration (s)", _num(o["duration_s"])],
         ["Languages", ", ".join(f"{k} ({v})" for k, v in o["languages"].items()) or "-"],
         ["Handed to a person", ", ".join(h["reason"] for h in o["handoffs"]) or "no"],
         ["Errors", str(len(o["errors"]))], ["Turns where personal details were withheld", str(o["turns_with_personal_details_withheld"])]])})
    out.append({"title": "Intent classification", "intro": "What the classifier decided each turn wanted. Turns inside an active "
                "conversation are read by that conversation first and need no classifier call.", "table": (
        ["Intent", "Turns"], [[k, str(v)] for k, v in sorted(i["distribution"].items(), key=lambda kv: -kv[1])] +
        [["**mean confidence**", _dec(i["mean_confidence"])], ["decided by the classifier", str(i["decided_by_classifier"])],
         ["decided by an active conversation", str(i["decided_by_context"])],
         ["low confidence (asked the user to clarify)", str(i["low_confidence_turns"])], ["asked for more detail", str(i["deep_requests"])]])})
    out.append({"title": "Routing through the orchestrator graph", "table": (["Path", "Turns"], [[p, str(n)] for p, n in
                sorted(r["routing"]["paths"].items(), key=lambda kv: -kv[1])]), "code": ("mermaid", r["routing"]["graph_mermaid"])})
    d = lat["decision_ms"]
    out.append({"title": "Latency", "intro": lat["note"], "table": (["Step", "Calls", "Mean ms", "p50 ms", "p95 ms", "Max ms"],
                [["**whole decision**", _num(d["n"]), _num(d["mean_ms"]), _num(d["p50_ms"]), _num(d["p95_ms"]), _num(d["max_ms"])]] +
                [[f"node: {k}", _num(v["n"]), _num(v["mean_ms"]), _num(v["p50_ms"]), _num(v["p95_ms"]), _num(v["max_ms"])] for k, v in lat["by_node"].items()])})
    cost = llm.get("estimated_cost")
    out.append({"title": "Model usage and prompt caching", "intro": (
        f"{llm['calls']} model calls; {_num(llm['input_tokens'])} input and {_num(llm['output_tokens'])} output tokens. "
        f"Sarvam's prompt cache served {_num(llm['provider_cached_tokens'])} input tokens ({_pct(llm['provider_cache_hit_rate'])}); "
        f"{llm['calls_avoided_by_app_cache']} model calls were avoided by the app caches."
        + (f" Estimated cost {cost['amount']} against {cost['without_prompt_cache']} without prompt caching ({cost['basis']})." if cost else "")),
        "table": (["Purpose", "Calls", "Input tokens", "Cached tokens", "Cached %", "Output tokens", "App-cache hits", "Mean ms", "p95 ms"],
                  [[k, _num(v["calls"]), _num(v["input_tokens"]), _num(v["cached_tokens"]),
                    _pct(v["cached_tokens"] / v["input_tokens"] if v["input_tokens"] else None), _num(v["output_tokens"]),
                    str(v["app_cache_hits"]), _num(v["mean_ms"]), _num(v["p95_ms"])] for k, v in llm["by_purpose"].items()])})
    out.append({"title": "App-level caches (in memory, never stored)", "table": (["Cache", "Hits", "Misses", "Hit rate"],
                [[k, str(v["hits"]), str(v["misses"]), _pct(v["hit_rate"])] for k, v in r["caches"].items()] or [["(none used)", "-", "-", "-"]])})
    out.append({"title": "Answer quality and guardrails", "table": (["Measure", "Value"], [
        ["Replies checked", str(q["replies_checked"])], ["Passed", str(q["passed"])], ["Blocked (safe fallback used)", str(q["blocked"])],
        ["Fallback rate", _pct(q["fallback_rate"])], ["Block reasons", ", ".join(f"{k}: {v}" for k, v in q["block_reasons"].items()) or "-"],
        ["Served from the verified-answer cache", str(q["served_from_verified_cache"])]])})
    out.append({"title": "Retrieval", "table": (["Measure", "Value"], [
        ["Turns that searched the knowledge base", str(rt["turns"])], ["Mean clauses used", _num(rt["mean_clauses"])],
        ["Mean best similarity", _dec(rt["mean_top_similarity"], 3)], ["Turns where nothing relevant was found", str(rt["turns_with_no_clause_found"])]])})
    if r["consents"]:
        out.append({"title": "Consent", "table": (["Purpose", "Event", "When"], [[c["purpose"], c["event"], _when(c["at"])] for c in r["consents"]])})
    if r["recommendations"]:
        out.append({"title": "Recommendations (ranges only, never exact figures)", "table": (["When", "Rules", "Profile ranges", "Ranked plans"], [
            [_when(x["at"]), str(x.get("rules_version", "-")), ", ".join(f"{k}={v}" for k, v in (x["profile_bands"] or {}).items()),
             ", ".join(f"#{p['rank']} {p['product']} ({p['score']})" for p in x["ranked"])] for x in r["recommendations"]])})
    if r["turns"]:
        out.append({"title": "Turn by turn", "table": (["#", "Intent", "Conf.", "Path", "ms", "Model calls", "Cached tok.", "Verdict", "Transcript / reply"], [
            [str(t["index"]), t["intent"] or "-", _dec(t["confidence"]), " > ".join(t["path"]), _num(t["decision_ms"]),
             str(len(t["llm_calls"])), _num(sum(c["cached_tokens"] for c in t["llm_calls"])),
             (t["verdict"] or "-") + (" (cache)" if t["from_cache"] else ""),
             (f"{t.get('transcript') or ''} -> {t.get('reply') or ''}" if "transcript" in t else "(text not included)")[:240]] for t in r["turns"]])})
    return out


def to_markdown(r: Dict[str, Any]) -> str:
    lines = [f"# Sahaj workflow report"]
    for s in sections(r):
        lines += ["", f"## {s['title']}"]
        if s.get("intro"):
            lines += ["", s["intro"]]
        if s.get("table"):
            head, rows = s["table"]
            lines += ["", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
            lines += ["| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in row) + " |" for row in rows]
        if s.get("code"):
            lines += ["", f"```{s['code'][0]}", s["code"][1], "```"]
    return "\n".join(lines) + "\n"


def to_html(r: Dict[str, Any]) -> str:
    e = html.escape
    body = []
    for s in sections(r):
        body.append(f"<h2>{e(s['title'])}</h2>")
        if s.get("intro"):
            body.append(f"<p>{e(s['intro'])}</p>")
        if s.get("table"):
            head, rows = s["table"]
            body.append("<div class=scroll><table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr></thead><tbody>"
                        + "".join("<tr>" + "".join(f"<td>{e(c.replace('**', ''))}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table></div>")
        if s.get("code"):
            body.append(f"<pre class=mermaid>{e(s['code'][1])}</pre>")
    return f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Sahaj workflow report</title>
<style>
:root{{--bg:#fff;--fg:#1d2330;--mut:#5d6677;--line:#dfe3ea;--head:#f3f5f8}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14171d;--fg:#e6e9ef;--mut:#9aa3b2;--line:#2a303b;--head:#1c212a}}}}
body{{margin:0 auto;max-width:1100px;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
h1{{margin:0 0 4px}}h2{{margin-top:32px;border-bottom:1px solid var(--line);padding-bottom:6px}}p{{color:var(--mut)}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}}th{{background:var(--head)}}
pre{{background:var(--head);padding:12px;border-radius:6px;overflow-x:auto;font-size:12px}}
</style>
<h1>Sahaj workflow report</h1>{''.join(body)}
<script type=module>import m from "{MERMAID}"; m.initialize({{startOnLoad:false}}); m.run({{querySelector:".mermaid"}}).catch(()=>{{}});</script>
</html>"""
