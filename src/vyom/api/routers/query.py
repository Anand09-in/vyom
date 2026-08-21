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
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from vyom.api.auth import CurrentUser, get_current_user
from vyom.api.deps import get_history_store, get_provider_dep, get_repo
from vyom.config import get_settings
from vyom.retrieve.pipeline import VyomState, build_pipeline
from vyom.retrieve.router import route
from vyom.store.history import HistoryStore, Turn

logger = logging.getLogger(__name__)
# Dedicated pure-JSON logger for structured completion events — configured
# in app.py's _configure_event_logger. Deliberately not `logger` above:
# that one has the normal timestamp/level/name prefix, which would break
# CloudWatch's JSON metric filters (see _log_completion below).
_events = logging.getLogger("vyom.events")
router = APIRouter(prefix="/query", tags=["query"], dependencies=[Depends(get_current_user)])

# Stored in place of a guardrail's actual refusal text when saving a turn to
# history. The refusal text itself ("...attempt to override Vyom's
# instructions...") reads as prompt-injection-flavored language — if stored
# verbatim, it gets fed back into classify_and_rewrite's/generate's prompts
# as conversation history on the *next* turn and can re-trigger the guardrail
# on an otherwise-unrelated follow-up question. This placeholder carries the
# same information (a question was asked and blocked) without the
# attack-shaped phrasing.
_BLOCKED_HISTORY_PLACEHOLDER = (
    "[This question was blocked by content-safety guardrails and was not answered.]"
)


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
    type: str                        # 'bse' | 'sebi' | 'rbi' | 'live'
    id: int | None = None
    company: str | None = None
    section: str | None = None
    circular_number: str | None = None
    title: str | None = None
    series_id: str | None = None
    period: str | None = None
    url: str | None = None
    published_at: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    sources_used: list[str]
    route_rationale: str
    latency_ms: int
    query_log_id: int
    session_id: str


class HistoryTurnOut(BaseModel):
    question: str
    answer: str


class ConversationSummaryOut(BaseModel):
    session_id: str
    title: str


class ConversationsOut(BaseModel):
    conversations: list[ConversationSummaryOut]


class HistoryOut(BaseModel):
    turns: list[HistoryTurnOut]


class CompanyOut(BaseModel):
    name: str
    bse_code: str | None = None


class CompaniesOut(BaseModel):
    companies: list[CompanyOut]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_session_id(req: QueryRequest) -> str:
    """A fresh client still gets a session — history just starts empty."""
    return req.session_id or str(uuid.uuid4())


def _log_completion(
    *,
    status: str,
    session_id: str,
    user_id: str,
    latency_ms: int,
    sources_used: list[str] | None = None,
    chunks_retrieved: int | None = None,
    guardrail_blocked: bool = False,
) -> None:
    """One structured line per completed request, at every return point in
    both /query and /query/stream — the basis for CloudWatch Logs Insights
    queries and metric filters once shipped by the CloudWatch Agent (see
    infra/main.tf). Plain logger.info() on a dedicated pure-JSON logger
    (app.py's _configure_event_logger), not a boto3 put_metric_data call —
    the app doesn't need to know CloudWatch exists, it just logs normally.
    status: 'ok' | 'blocked' | 'error'."""
    _events.info(json.dumps({
        "event": "query_complete",
        "status": status,
        "session_id": session_id,
        "user_id": user_id,
        "latency_ms": latency_ms,
        "sources_used": sources_used or [],
        "chunks_retrieved": chunks_retrieved,
        "guardrail_blocked": guardrail_blocked,
    }))


async def _make_initial_state(
    req: QueryRequest, user_id: str, session_id: str, history_store: HistoryStore, settings
) -> VyomState:
    recent = await history_store.get_recent(user_id, session_id, settings.history_recent_turns)
    return VyomState(
        query=req.query,
        standalone_query=req.query,
        rewritten_query=req.query,
        company=req.company,
        history_recent=[{"question": t.question, "answer": t.answer} for t in recent],
        route=None,
        filing_chunks=[],
        circular_chunks=[],
        rbi_chunks=[],
        live_results=[],
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
    history_store: HistoryStore = Depends(get_history_store),
    current_user: CurrentUser = Depends(get_current_user),
) -> QueryResponse:
    settings = get_settings()
    enabled = req.sources or settings.sources
    session_id = _resolve_session_id(req)

    t0 = time.monotonic()

    # Fast up-front check on the raw query, before any retrieval work runs —
    # an obvious injection attempt gets rejected without paying for
    # embedding/search/rerank/HyDE first. See Provider.check_guardrail.
    block_message = await asyncio.to_thread(provider.check_guardrail, req.query)
    if block_message is not None:
        latency = int((time.monotonic() - t0) * 1000)
        log_id = await repo.log_query(
            user_id=current_user.user_id,
            session_id=session_id,
            query=req.query,
            rewritten_query=None,
            sources_used=[],
            chunks_retrieved=0,
            latency_ms=latency,
            tokens_used=0,
            provider=settings.provider,
        )
        await history_store.append(
            current_user.user_id, session_id, req.query, _BLOCKED_HISTORY_PLACEHOLDER
        )
        _log_completion(
            status="blocked", session_id=session_id, user_id=current_user.user_id,
            latency_ms=latency,
        )
        return QueryResponse(
            answer=block_message,
            citations=[],
            sources_used=[],
            route_rationale="Blocked by input guardrail",
            latency_ms=latency,
            query_log_id=log_id,
            session_id=session_id,
        )

    pipeline = build_pipeline(
        provider=provider,
        repo=repo,
        top_k=settings.top_k,
        rerank_top_n=settings.rerank_top_n,
        max_loops=settings.max_rewrite_loops,
        enabled_sources=enabled,
        tavily_api_key=settings.tavily_api_key,
    )

    try:
        initial_state = await _make_initial_state(
            req, current_user.user_id, session_id, history_store, settings
        )
        result = await pipeline.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("Pipeline error for query: %s", req.query)
        _log_completion(
            status="error", session_id=session_id, user_id=current_user.user_id,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    latency = int((time.monotonic() - t0) * 1000)
    decision = result["route"]

    log_id = await repo.log_query(
        user_id=current_user.user_id,
        session_id=session_id,
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

    await history_store.append(
        current_user.user_id,
        session_id,
        req.query,
        _BLOCKED_HISTORY_PLACEHOLDER if result.get("guardrail_blocked") else result["answer"],
    )
    _log_completion(
        status="blocked" if result.get("guardrail_blocked") else "ok",
        session_id=session_id, user_id=current_user.user_id, latency_ms=latency,
        sources_used=result.get("sources_used", []),
        chunks_retrieved=(
            len(result.get("filing_chunks", []))
            + len(result.get("circular_chunks", []))
            + len(result.get("rbi_chunks", []))
            + len(result.get("live_results", []))
        ),
        guardrail_blocked=bool(result.get("guardrail_blocked")),
    )

    return QueryResponse(
        answer=result["answer"],
        citations=[CitationOut(**c) for c in result.get("citations", [])],
        sources_used=result.get("sources_used", []),
        route_rationale=decision.rationale,
        latency_ms=latency,
        query_log_id=log_id,
        session_id=session_id,
    )


# ── POST /query/stream ────────────────────────────────────────────────────────

@router.post("/stream")
async def query_stream(
    req: QueryRequest,
    repo=Depends(get_repo),
    provider=Depends(get_provider_dep),
    history_store: HistoryStore = Depends(get_history_store),
    current_user: CurrentUser = Depends(get_current_user),
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
    session_id = _resolve_session_id(req)

    async def event_generator() -> AsyncIterator[dict]:
        t0 = time.monotonic()

        # Fast up-front check on the raw query, before any retrieval work
        # runs or the "route" preview is even emitted — see
        # Provider.check_guardrail and the /query handler above.
        block_message = await asyncio.to_thread(provider.check_guardrail, req.query)
        if block_message is not None:
            yield {
                "event": "route",
                "data": json.dumps({"sources": [], "rationale": "Blocked by input guardrail"}),
            }
            yield {"event": "token", "data": json.dumps(block_message)}
            await history_store.append(
                current_user.user_id, session_id, req.query, _BLOCKED_HISTORY_PLACEHOLDER
            )
            _log_completion(
                status="blocked", session_id=session_id, user_id=current_user.user_id,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [],
                    "sources_used": [],
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "session_id": session_id,
                }),
            }
            return

        # Provisional preview based on the raw query, emitted immediately so
        # the UI can show "Searching BSE + RBI…" without waiting on the
        # pipeline. When there's conversation history, the pipeline's own
        # classify_and_rewrite node re-routes against the *condensed*
        # standalone query — the authoritative sources_used/rationale ride
        # on the "done" event below and can differ from this preview for
        # follow-up questions (e.g. "what about last year?" only resolves
        # to the right sources once history has been folded in).
        preview = route(req.query, enabled)
        yield {
            "event": "route",
            "data": json.dumps({
                "sources": preview.sources,
                "rationale": preview.rationale,
            }),
        }

        pipeline = build_pipeline(
            provider=provider,
            repo=repo,
            top_k=settings.top_k,
            rerank_top_n=settings.rerank_top_n,
            max_loops=settings.max_rewrite_loops,
            enabled_sources=enabled,
            tavily_api_key=settings.tavily_api_key,
        )

        initial_state = await _make_initial_state(
            req, current_user.user_id, session_id, history_store, settings
        )
        try:
            result = await pipeline.ainvoke(initial_state)
        except Exception:
            # Any unhandled pipeline failure would otherwise abort the SSE
            # stream outright — sse_starlette surfaces that to the client as
            # a bare connection failure ("Something went wrong"), not a
            # readable message. Degrade to the same token/done shape the
            # early guardrail check uses instead.
            logger.exception("Pipeline error for streamed query: %s", req.query)
            error_message = (
                "Something went wrong while generating a response. Please try again."
            )
            yield {"event": "token", "data": json.dumps(error_message)}
            await history_store.append(current_user.user_id, session_id, req.query, error_message)
            _log_completion(
                status="error", session_id=session_id, user_id=current_user.user_id,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [],
                    "sources_used": [],
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "session_id": session_id,
                }),
            }
            return

        # Stream answer word by word, preserving the model's original
        # whitespace (newlines, blank lines between list items, etc.) —
        # each token is one word plus whatever whitespace immediately
        # follows it. JSON-encoded so a literal newline survives SSE's
        # line-based framing intact, and so the client can dispatch
        # purely on `event:` type instead of guessing from content shape.
        for match in re.finditer(r"\S+\s*", result["answer"]):
            yield {"event": "token", "data": json.dumps(match.group())}
            await asyncio.sleep(0)   # yield to event loop between tokens

        await history_store.append(
            current_user.user_id,
            session_id,
            req.query,
            _BLOCKED_HISTORY_PLACEHOLDER if result.get("guardrail_blocked") else result["answer"],
        )
        _log_completion(
            status="blocked" if result.get("guardrail_blocked") else "ok",
            session_id=session_id, user_id=current_user.user_id,
            latency_ms=result.get("latency_ms", 0),
            sources_used=result.get("sources_used", []),
            chunks_retrieved=(
                len(result.get("filing_chunks", []))
                + len(result.get("circular_chunks", []))
                + len(result.get("rbi_chunks", []))
                + len(result.get("live_results", []))
            ),
            guardrail_blocked=bool(result.get("guardrail_blocked")),
        )

        # Final metadata
        yield {
            "event": "done",
            "data": json.dumps({
                "citations": result.get("citations", []),
                "sources_used": result.get("sources_used", []),
                "latency_ms": result.get("latency_ms", 0),
                "session_id": session_id,
            }),
        }

    return EventSourceResponse(event_generator())


# ── GET /query/companies ─────────────────────────────────────────────────────

@router.get("/companies", response_model=CompaniesOut)
async def get_companies(repo=Depends(get_repo)) -> CompaniesOut:
    """Every company with at least one ingested filing — backs the
    frontend's company autocomplete. Reflects the real database, not a
    hardcoded list that can drift out of sync with what's actually
    ingested."""
    companies = await repo.list_companies()
    return CompaniesOut(companies=[CompanyOut(**c) for c in companies])


# ── GET /query/conversations ──────────────────────────────────────────────────

@router.get("/conversations", response_model=ConversationsOut)
async def get_conversations(
    history_store: HistoryStore = Depends(get_history_store),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConversationsOut:
    """This user's 10 most-recently-active conversations, for the sidebar."""
    summaries = await history_store.list_recent(current_user.user_id, 10)
    return ConversationsOut(
        conversations=[
            ConversationSummaryOut(session_id=s.session_id, title=s.title) for s in summaries
        ]
    )


# ── GET / DELETE /query/history/{session_id} ─────────────────────────────────

@router.get("/history/{session_id}", response_model=HistoryOut)
async def get_history(
    session_id: str,
    history_store: HistoryStore = Depends(get_history_store),
    current_user: CurrentUser = Depends(get_current_user),
) -> HistoryOut:
    """Every turn ever stored for this session — for the frontend to restore
    the visible thread after a page reload. Unbounded (not just the last 5
    the LLM sees — see history_recent_turns in config.py)."""
    turns = await history_store.get_all(current_user.user_id, session_id)
    return HistoryOut(turns=[HistoryTurnOut(question=t.question, answer=t.answer) for t in turns])


@router.delete("/history/{session_id}", status_code=204)
async def delete_history(
    session_id: str,
    history_store: HistoryStore = Depends(get_history_store),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    """Explicit clear — history has no TTL, so this is the only way it goes away."""
    await history_store.delete(current_user.user_id, session_id)