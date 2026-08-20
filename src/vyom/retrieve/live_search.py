"""Live web search — the one Vyom source that isn't pre-ingested.

Unlike BSE/SEBI/RBI (Postgres tables, hybrid dense+sparse search via
repo.hybrid_search_*), there's nothing to embed or rank here: Tavily already
returns ranked, LLM-cleaned results, so this is a plain HTTP call, not a
repo.py method.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str
    published_at: str | None


async def search_web(query: str, api_key: str, max_results: int = 5) -> list[WebResult]:
    """Query Tavily for current web results. Never raises — a Tavily outage
    or timeout degrades to zero live results rather than failing the whole
    query, matching how the other sources return [] when nothing matches."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TAVILY_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily search failed for %r: %s", query, exc)
        return []

    return [
        WebResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("content", ""),
            published_at=r.get("published_date") or None,
        )
        for r in data.get("results", [])
    ]
