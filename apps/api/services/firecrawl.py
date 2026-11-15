"""Current India-focused insurance and lending search backed by Firecrawl."""
import re

import httpx

import config
from services import telemetry
from trust.pii import Vault, normalise_digits


class FirecrawlUnavailable(RuntimeError):
    pass


class FirecrawlError(RuntimeError):
    pass


def _query(value: str, domain: str) -> str:
    clean = " ".join(Vault().mask(normalise_digits(value)).split())
    clean = re.sub(r"(?i)(?:₹\s*)?\b\d[\d,.]*(?:\s*(?:lakh|lakhs|crore|crores|years?|months?|years? old|%|percent))?\b", " ", clean)
    clean = " ".join(clean.split())
    if not clean:
        raise ValueError("A search query is required.")
    topic = "insurance" if domain == "insurance" else "loan lending"
    if topic.split()[0] not in clean.lower() and (domain != "insurance" or "insurer" not in clean.lower()):
        clean += f" India {topic}"
    if domain == "loan" and not any(term in clean.lower() for term in ("official", "rbi", "bank", "nbfc", "lender")):
        clean += " official lender information"
    return clean[:500]


def _results(payload: dict, limit: int) -> list[dict]:
    data = payload.get("data", payload)
    results = []
    for category in ("web", "news"):
        items = data.get(category, []) if isinstance(data, dict) else []
        for item in items[:limit]:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            results.append({
                "type": category,
                "title": str(item.get("title") or item.get("url"))[:300],
                "url": str(item["url"])[:2000],
                "description": str(item.get("description") or item.get("snippet") or "")[:1500],
                "content": str(item.get("markdown") or item.get("content") or item.get("snippet") or "")[:4000],
            })
    return results


async def search_web(query: str, domain: str, limit: int | None = None) -> dict:
    if domain not in ("insurance", "loan"):
        raise ValueError("Search domain must be insurance or loan.")
    if not config.FIRECRAWL_API_KEY:
        raise FirecrawlUnavailable("Set FIRECRAWL_API_KEY to enable web search.")
    clean = _query(query, domain)
    result_limit = max(1, min(limit or config.FIRECRAWL_SEARCH_LIMIT, 10))
    payload = {
        "query": clean,
        "limit": result_limit,
        "sources": [{"type": "web"}, {"type": "news"}],
        "country": "IN",
        "location": "India",
        "safe": True,
        "highlights": True,
        "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
        "timeout": int(config.FIRECRAWL_TIMEOUT_SECONDS * 1000),
    }
    try:
        async with httpx.AsyncClient(timeout=config.FIRECRAWL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{config.FIRECRAWL_BASE_URL}/search",
                headers={"Authorization": f"Bearer {config.FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise FirecrawlError("Web search failed. Try again shortly.") from exc
    if not isinstance(body, dict) or body.get("success") is False:
        raise FirecrawlError("Web search failed. Try again shortly.")
    results = _results(body, result_limit)
    credits_used = body.get("creditsUsed")
    if isinstance(credits_used, bool) or not isinstance(credits_used, (int, float)) or credits_used < 0:
        credits_used = None
    telemetry.meter({"kind": "websearch", "provider": "firecrawl", "model": "v2/search",
                     "purpose": f"{domain}_market", "units": credits_used or 0,
                     "cost_usd": (credits_used or 0) * config.FIRECRAWL_PRICE_PER_CREDIT_USD})
    return {"query": clean, "results": results, "results_count": len(results), "credits_used": credits_used,
            "provider": "firecrawl"}


async def search_insurance(query: str, limit: int | None = None) -> dict:
    return await search_web(query, "insurance", limit)


def sources_for(results: list[dict]) -> dict[str, str]:
    return {f"web:{index}": "\n".join(part for part in (
        f"Type: {item['type']}", f"Title: {item['title']}", f"URL: {item['url']}",
        f"Description: {item['description']}", f"Page content: {item['content']}") if part)
        for index, item in enumerate(results, 1)}
