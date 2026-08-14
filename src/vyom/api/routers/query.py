"""POST /query and POST /query/stream — the core Vyom endpoints.

/query        — returns a complete answer in one response (JSON)
/query/stream — streams the answer token by token over SSE

Both endpoints run the full LangGraph pipeline:
  classify_and_rewrite → retrieve_all → grade → generate

The stream endpoint emits three SSE event types:
  event: route   — which sources were selected and why
  event: token   — one word of the answer at a time
  event: done    — citations + latency metadata
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from vyom.api.deps import get_provider_dep, get_repo
from vyom.config import get_settings
from vyom.retrieve.pipeline import VyomState, build_pipeline
from vyom.retrieve.router import route

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])


# ── Request / response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    company: str | None = Field(
        default=None,
        description="Optional company filter, e.g. 'HDFCBANK' or 'Reliance'",
    )
    session_id: str | None = None
    sources: list[str] | None = Field(
        default=None,
        description="Override the router. e.g. ['bse', 'rbi']. Leave null to auto-route.",
    )


class CitationOut(BaseModel):
    type: str                        # 'bse' | 'sebi' | 'rbi'
    id: int | None = None
    company: str | None = None
    section: str | None = None
    circular_number: str | None = None
    title: str | None = None
    series_id: str | None = None
    period: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    sources_used: list[str]
    route_rationale: str
    latency_ms: int
    query_log_id: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_initial_state(req: QueryRequest, decision) -> VyomState:
    return VyomState(
        query=req.query,
        rewritten_query=req.query,
        company=req.company,
        route=decision,
        filing_chunks=[],
        circular_chunks=[],
        rbi_chunks=[],
        answer="",
        citations=[],
        sources_used=[],
        loop_count=0,
        tokens_used=0,
        latency_ms=0,
    )


# ── POST /query ───────────────────────────────────────────────────────────────

@router.post("", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    repo=Depends(get_repo),
    provider=Depends(get_provider_dep),
) -> QueryResponse:
    settings = get_settings()
    enabled = req.sources or settings.sources
    decision = route(req.query, enabled)

    pipeline = build_pipeline(
        provider=provider,
        repo=repo,
        top_k=settings.top_k,
        rerank_top_n=settings.rerank_top_n,
        max_loops=settings.max_rewrite_loops,
        enabled_sources=enabled,
    )

    t0 = time.monotonic()
    try:
        result = await pipeline.ainvoke(_make_initial_state(req, decision))
    except Exception as exc:
        logger.exception("Pipeline error for query: %s", req.query)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    latency = int((time.monotonic() - t0) * 1000)

    log_id = await repo.log_query(
        session_id=req.session_id,
        query=req.query,
        rewritten_query=result.get("rewritten_query"),
        sources_used=result.get("sources_used", []),
        chunks_retrieved=(
            len(result.get("filing_chunks", []))
            + len(result.get("circular_chunks", []))
            + len(result.get("rbi_chunks", []))
        ),
        latency_ms=latency,
        tokens_used=result.get("tokens_used", 0),
        provider=settings.provider,
    )

    return QueryResponse(
        answer=result["answer"],
        citations=[CitationOut(**c) for c in result.get("citations", [])],
        sources_used=result.get("sources_used", []),
        route_rationale=decision.rationale,
        latency_ms=latency,
        query_log_id=log_id,
    )


# ── POST /query/stream ────────────────────────────────────────────────────────

@router.post("/stream")
async def query_stream(
    req: QueryRequest,
    repo=Depends(get_repo),
    provider=Depends(get_provider_dep),
):
    """
    SSE streaming endpoint.
    The client receives three event types in order:
      1. route  — routing decision (which sources + rationale)
      2. token  — one word of the answer, space-separated
      3. done   — citations + latency when generation completes
    """
    settings = get_settings()
    enabled = req.sources or settings.sources

    async def event_generator() -> AsyncIterator[dict]:
        decision = route(req.query, enabled)

        # Emit routing decision immediately so the UI can show "Searching BSE + RBI…"
        yield {
            "event": "route",
            "data": json.dumps({
                "sources": decision.sources,
                "rationale": decision.rationale,
            }),
        }

        pipeline = build_pipeline(
            provider=provider,
            repo=repo,
            top_k=settings.top_k,
            rerank_top_n=settings.rerank_top_n,
            max_loops=settings.max_rewrite_loops,
            enabled_sources=enabled,
        )

        result = await pipeline.ainvoke(_make_initial_state(req, decision))

        # Stream answer word by word, preserving the model's original
        # whitespace (newlines, blank lines between list items, etc.) —
        # each token is one word plus whatever whitespace immediately
        # follows it. JSON-encoded so a literal newline survives SSE's
        # line-based framing intact, and so the client can dispatch
        # purely on `event:` type instead of guessing from content shape.
        for match in re.finditer(r"\S+\s*", result["answer"]):
            yield {"event": "token", "data": json.dumps(match.group())}
            await asyncio.sleep(0)   # yield to event loop between tokens

        # Final metadata
        yield {
            "event": "done",
            "data": json.dumps({
                "citations": result.get("citations", []),
                "sources_used": result.get("sources_used", []),
                "latency_ms": result.get("latency_ms", 0),
            }),
        }

    return EventSourceResponse(event_generator())