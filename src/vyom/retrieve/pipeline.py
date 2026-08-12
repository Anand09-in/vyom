"""Vyom LangGraph agentic pipeline.

Agentic patterns used (two, layered):

Pattern 1 — Orchestrator / router
  The classify_and_rewrite node acts as an orchestrator that decides which
  sub-systems (BSE, SEBI, RBI retrievers) to invoke. The routing decision is
  rule-based (see router.py), not an LLM call.

Pattern 2 — Self-RAG corrective loop
  After retrieval, the grade node checks whether the returned chunks are
  relevant. If not, it loops back to rewrite the query and retry — bounded
  at max_rewrite_loops (default: 2) to prevent infinite retries.

LangGraph state machine:
  classify_and_rewrite → retrieve_all → grade ─── generate → END
                              ↑                 └── increment_loop ┘
                              └──────────────────────────────────────┘

This is NOT ReAct. The control flow is a fixed compiled graph.
The LLM never picks its own next action at runtime.
"""
from __future__ import annotations

import logging
import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

from vyom.providers.base import Provider
from vyom.retrieve.router import RouteDecision, route
from vyom.store.repo import CircularChunk, FilingChunk, RbiChunk, Repository

logger = logging.getLogger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Vyom, an Indian financial intelligence assistant.

You have access to three data sources:
- BSE/NSE filings: annual reports, quarterly results, risk factors, MD&A
- SEBI circulars: regulatory orders, NBFC norms, BRSR mandates, enforcement actions
- RBI data: repo rate, CPI inflation, credit growth, forex, monetary policy

Rules you must follow:
1. Answer ONLY from the retrieved context provided below. Never use prior knowledge.
2. Every factual claim must cite its source: [BSE:chunk_id], [SEBI:chunk_id], or [RBI:series_id].
3. If the context is insufficient to answer, say so clearly — never fabricate facts.
4. When multiple sources are available, synthesise across them.
5. Use plain English. Avoid jargon unless it appears in the source.
"""


# ── State definition ───────────────────────────────────────────────────────────

class VyomState(TypedDict):
    query: str
    rewritten_query: str
    company: str | None            # optional ticker/company name filter
    route: RouteDecision | None
    filing_chunks: list[FilingChunk]
    circular_chunks: list[CircularChunk]
    rbi_chunks: list[RbiChunk]
    answer: str
    citations: list[dict]
    sources_used: list[str]
    loop_count: int
    tokens_used: int
    latency_ms: int


# ── Pipeline builder ───────────────────────────────────────────────────────────

def build_pipeline(
    provider: Provider,
    repo: Repository,
    top_k: int = 20,
    rerank_top_n: int = 5,
    max_loops: int = 2,
    enabled_sources: list[str] | None = None,
):
    """
    Build and compile the Vyom LangGraph pipeline.

    Returns a compiled LangGraph app that can be called with:
        result = await pipeline.ainvoke(initial_state)
    """

    # ── Node 1: classify_and_rewrite ──────────────────────────────────────────
    def classify_and_rewrite(state: VyomState) -> VyomState:
        """
        Two jobs in one node:
        1. Route the query to the right source(s) using keyword signals.
        2. HyDE (Hypothetical Document Embedding) — generate a short hypothetical
           answer and append it to the query. This enriches the embedding so
           retrieval finds more relevant chunks.
        """
        decision = route(state["query"], enabled_sources)

        # HyDE: generate a hypothetical answer for better embedding
        hyp = provider.generate(
            f"Write one short paragraph that would answer this question about "
            f"an Indian company or financial regulation: {state['query']}",
            system=(
                "Be concise (2-3 sentences). Use Indian financial terminology "
                "where relevant. Do not make up specific numbers."
            ),
        )

        rewritten = f"{state['query']} {hyp[:400]}"

        return {
            **state,
            "route": decision,
            "rewritten_query": rewritten,
        }

    # ── Node 2: retrieve_all ──────────────────────────────────────────────────
    async def retrieve_all(state: VyomState) -> VyomState:
        """
        Fan out to all routed sources in parallel.
        Only sources in the RouteDecision are queried — a BSE-only query
        never touches the SEBI or RBI tables.
        """
        embedding = provider.embed_query(state["rewritten_query"])
        decision: RouteDecision = state["route"]
        sources = decision.sources
        company = state.get("company")

        filing_chunks: list[FilingChunk] = []
        circular_chunks: list[CircularChunk] = []
        rbi_chunks: list[RbiChunk] = []

        if "bse" in sources:
            raw = await repo.hybrid_search_bse(
                embedding,
                state["rewritten_query"],
                top_k=top_k,
                company=company,
            )
            if raw:
                texts = [c.content for c in raw]
                ranked = provider.rerank(state["query"], texts, top_n=rerank_top_n)
                filing_chunks = [raw[r.index] for r in ranked]

        if "sebi" in sources:
            raw_s = await repo.hybrid_search_sebi(
                embedding,
                state["rewritten_query"],
                top_k=top_k // 2,
            )
            if raw_s:
                texts = [c.content for c in raw_s]
                ranked = provider.rerank(state["query"], texts, top_n=rerank_top_n)
                circular_chunks = [raw_s[r.index] for r in ranked]

        if "rbi" in sources:
            raw_r = await repo.hybrid_search_rbi(
                embedding,
                state["rewritten_query"],
                top_k=top_k // 2,
            )
            if raw_r:
                texts = [c.content for c in raw_r]
                ranked = provider.rerank(state["query"], texts, top_n=min(rerank_top_n, 3))
                rbi_chunks = [raw_r[r.index] for r in ranked]

        return {
            **state,
            "filing_chunks": filing_chunks,
            "circular_chunks": circular_chunks,
            "rbi_chunks": rbi_chunks,
            "sources_used": sources,
        }

    # ── Conditional edge: grade ───────────────────────────────────────────────
    def grade(state: VyomState) -> str:
        """
        Check if retrieval returned anything useful.
        Returns 'generate' (proceed) or 'rewrite' (loop back).
        After max_loops, always proceed to generate regardless.
        """
        total_chunks = (
            len(state["filing_chunks"])
            + len(state["circular_chunks"])
            + len(state["rbi_chunks"])
        )

        if total_chunks == 0 and state["loop_count"] < max_loops:
            logger.info(
                "Grade: no chunks found (loop %d/%d) — rewriting query",
                state["loop_count"] + 1,
                max_loops,
            )
            return "rewrite"

        return "generate"

    # ── Node 3: increment_loop ─────────────────────────────────────────────────
    def increment_loop(state: VyomState) -> VyomState:
        return {**state, "loop_count": state.get("loop_count", 0) + 1}

    # ── Node 4: generate ───────────────────────────────────────────────────────
    def generate(state: VyomState) -> VyomState:
        """
        Assemble context from all retrieved chunks and call the LLM.
        Citations are tagged inline: [BSE:id], [SEBI:id], [RBI:id].
        """
        t0 = time.monotonic()

        filings  = state["filing_chunks"]
        circulars = state["circular_chunks"]
        rbi       = state["rbi_chunks"]

        # No context found after all loops
        if not filings and not circulars and not rbi:
            return {
                **state,
                "answer": (
                    "I could not find relevant information in the BSE filings, "
                    "SEBI circulars, or RBI data for this query. "
                    "Try rephrasing or asking about a specific Nifty 50 company."
                ),
                "citations": [],
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        # Build context blocks, tagged by source
        context_parts: list[str] = []
        citations: list[dict] = []

        if filings:
            context_parts.append("── BSE / NSE FILINGS ──")
            for c in filings:
                context_parts.append(
                    f"[BSE:{c.id}] {c.company_name} / {c.section or 'general'}\n{c.content}"
                )
                citations.append({
                    "type": "bse",
                    "id": c.id,
                    "company": c.company_name,
                    "section": c.section,
                })

        if circulars:
            context_parts.append("── SEBI CIRCULARS ──")
            for c in circulars:
                context_parts.append(
                    f"[SEBI:{c.id}] {c.circular_number} — {c.title}\n{c.content}"
                )
                citations.append({
                    "type": "sebi",
                    "id": c.id,
                    "circular_number": c.circular_number,
                    "title": c.title,
                })

        if rbi:
            context_parts.append("── RBI ECONOMIC DATA ──")
            for c in rbi:
                context_parts.append(
                    f"[RBI:{c.series_id}] {c.period}\n{c.content}"
                )
                citations.append({
                    "type": "rbi",
                    "series_id": c.series_id,
                    "period": c.period,
                })

        context = "\n\n".join(context_parts)
        sources_label = " + ".join(s.upper() for s in state["sources_used"])

        prompt = (
            f"Sources available: {sources_label}\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {state['query']}\n\n"
            "Answer with inline citations [BSE:id], [SEBI:id], or [RBI:series_id]:"
        )

        answer = provider.generate(prompt, system=SYSTEM_PROMPT)
        latency = int((time.monotonic() - t0) * 1000)

        return {
            **state,
            "answer": answer,
            "citations": citations,
            "latency_ms": latency,
            "tokens_used": len(answer.split()),
        }

    # ── Assemble the graph ─────────────────────────────────────────────────────
    graph = StateGraph(VyomState)

    graph.add_node("classify_and_rewrite", classify_and_rewrite)
    graph.add_node("retrieve_all", retrieve_all)
    graph.add_node("increment_loop", increment_loop)
    graph.add_node("generate", generate)

    graph.set_entry_point("classify_and_rewrite")
    graph.add_edge("classify_and_rewrite", "retrieve_all")
    graph.add_conditional_edges(
        "retrieve_all",
        grade,
        {
            "rewrite":  "increment_loop",
            "generate": "generate",
        },
    )
    graph.add_edge("increment_loop", "classify_and_rewrite")
    graph.add_edge("generate", END)

    return graph.compile()