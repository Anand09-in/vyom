# Concepts

The ideas behind Vyom's design, in the order you'd hit them tracing a query through the system.

## Provider abstraction

All model calls (embed, generate, stream, rerank) go through one abstract interface: [`Provider`](../src/vyom/providers/base.py). Two concrete implementations exist:

- **`LocalProvider`** — `nomic-embed-text-v1.5` for embeddings, `bge-reranker-v2-m3` for reranking, Ollama for generation. Runs entirely on your machine, costs nothing, used for dev.
- **`BedrockProvider`** — generation only, via Bedrock's Converse API (Mistral Large 3). Embedding and reranking are **not** swapped out — `BedrockProvider` delegates those straight to a `LocalProvider` instance internally, since query-time embeddings have to use the exact same model as whatever embedded the corpus at ingest time, and Bedrock's own rerank API has quota/IAM limitations that made local reranking the more reliable choice anyway.

The rest of the codebase (router, pipeline, API) only ever imports `Provider`, never a concrete class. Switching `VYOM_PROVIDER=local` → `VYOM_PROVIDER=bedrock` in `.env` swaps generation with no code changes — that's the whole point of the seam. It does **not** mean "everything moves to AWS"; embedding and reranking stay local either way.

Heavy ML imports (`torch`, `sentence-transformers`) are deferred inside `@cached_property` methods rather than imported at module load time, so importing the package stays fast. This matters for the deploy target too: since embed/rerank always run locally regardless of provider, the deployed instance needs `torch` installed either way — see "Deployment" below for why that ruled out Lambda.

## Hybrid search (dense + sparse + RRF)

Each source table (`filing_chunks`, `circular_chunks`, `rbi_chunks`) is searched two ways in the same SQL query:

- **Dense** — cosine similarity between the query embedding and each chunk's `vector(512)` column, using an HNSW index (`vector_cosine_ops`) for approximate nearest-neighbor search. Good at semantic/paraphrase matches.
- **Sparse** — Postgres full-text search (`tsvector` + `plainto_tsquery`, ranked with `ts_rank_cd`) over a GIN index. Good at exact keyword/acronym matches (e.g. "NPA", "CRAR") that embeddings sometimes blur.

Neither is reliable alone in a finance domain full of exact terminology mixed with natural language questions. **Reciprocal Rank Fusion (RRF)** merges the two ranked lists: each result gets `1 / (60 + rank)` from whichever list(s) it appears in, scores are summed, and the merged list is re-sorted. The constant `60` is the standard RRF damping factor — it flattens the impact of rank 1 vs. rank 2 so one list doesn't dominate. All of this happens as CTEs in a single query (see `hybrid_search_bse` etc. in [repo.py](../src/vyom/store/repo.py)) — one round trip, no merging in Python.

## Contextual retrieval (context prefix)

A chunk pulled out of a 40-page annual report loses context — "revenue grew 12%" doesn't say whose revenue, or which quarter. [`add_context_prefix`](../src/vyom/ingest/chunker.py) prepends a short document-level summary ("From HDFC Bank's FY2025 annual report:") to each chunk before it's embedded and indexed, so the chunk is self-contained even when retrieved in isolation. This is the same idea popularized as "contextual retrieval" — it costs a little extra text per chunk and meaningfully improves retrieval precision.

## Keyword router (not an LLM)

[`router.py`](../src/vyom/retrieve/router.py) decides which of BSE / SEBI / RBI (or a cross-source combination) a query should hit — using regex keyword-signal lists scored per source, not an LLM call. The reasoning, stated directly in the module docstring: Indian financial vocabulary (NPA, CRAR, repo rate, BRSR, ...) is finite and well-known in advance, so a deterministic classifier is free and adds zero latency, where an LLM router would cost ~500 tokens and 1-2 seconds per query for a decision that doesn't need that much intelligence. Cross-source intent is detected separately via its own trigger patterns (e.g. "how does inflation affect bank NPAs" combines an RBI concept with a BSE concept).

## Agentic pipeline (LangGraph, Self-RAG)

The retrieval flow is a compiled state machine, not a ReAct loop where the LLM freely picks tool calls. [`pipeline.py`](../src/vyom/retrieve/pipeline.py) fixes the graph shape in advance:

```
classify_and_rewrite → retrieve_all → grade ──→ generate → END
        ↑                                │
        └──────────── increment_loop ────┘  (only if grade says "rewrite")
```

Two techniques are layered into this:

- **Orchestrator/router pattern** — `classify_and_rewrite` decides which sub-retrievers (BSE/SEBI/RBI) to invoke, using the rule-based router above. It also does **HyDE** (Hypothetical Document Embedding): it asks the LLM to write a short hypothetical answer to the query, then appends that to the query before embedding it. A hypothetical answer written in the same style as the target documents tends to embed closer to the real answer than the bare question does, which improves recall.
- **Self-RAG corrective loop** — after retrieval, `grade` checks whether any chunks came back. If retrieval was empty and the loop budget (`max_rewrite_loops`, default 2) isn't exhausted, it loops back through `increment_loop` to rewrite and retry rather than immediately generating an unsupported answer. Once loops are exhausted or chunks are found, it proceeds to `generate` regardless — bounded, so it can't loop forever.

The LLM never chooses the next graph node at runtime — the only thing it decides is the content of the rewritten query and the final answer. That's a deliberate simplicity/predictability trade-off versus a fully autonomous agent.

## Reranking

Hybrid search over-fetches (`top_k`, default 20) because RRF is a cheap, approximate way to get a decent candidate set fast. Those candidates are then passed through `rerank()` — always the local `bge-reranker-v2-m3` cross-encoder, regardless of `VYOM_PROVIDER` — which scores each `(query, document)` pair directly and is much more accurate than embedding similarity, but far too slow to run over the whole table. Retrieve broad and cheap, then rerank narrow and precise, keeping only `rerank_top_n` (default 5) chunks per source for generation.

## Grounded generation with citations

`generate` builds a context block tagged by source (`[BSE:id]`, `[SEBI:id]`, `[RBI:series_id]`) and instructs the model (via `SYSTEM_PROMPT` in [pipeline.py](../src/vyom/retrieve/pipeline.py)) to answer only from that context, cite every claim, and say so explicitly rather than fabricate an answer when context is insufficient. The `citations` returned alongside the answer are built directly from the retrieved chunk metadata, not parsed out of the LLM's text — so citations are guaranteed accurate even if the model's inline tags are imperfect.

## RBI data: narrative chunks, not raw numbers

`rbi_observations` stores raw time-series values (date, value), but those aren't what gets embedded or searched — a schema comment in [schema.sql](../src/vyom/store/schema.sql) notes raw numbers don't embed usefully. Instead, `rbi_chunks` stores human-readable narrative summaries per period ("Repo rate held at 6.5% in Q3 2024 amid..."), and those narrative chunks are what dense/sparse search and generation actually operate on.

## Config as the single source of truth

[`config.py`](../src/vyom/config.py) defines one `pydantic-settings` `Settings` class with an `VYOM_` env prefix, loaded once via an `lru_cache`d `get_settings()`. Nothing else in the codebase reads `os.environ` directly — this is what makes `.env.example` the complete list of every tunable in the system, and makes local vs. Bedrock, or which sources are enabled, a config change rather than a code change.

## Deployment: one EC2 instance, not Lambda

The FastAPI `app` object in [app.py](../src/vyom/api/app.py) is created once and reused everywhere. A Mangum-wrapped Lambda entrypoint exists ([lambda_handler.py](../src/vyom/api/lambda_handler.py)) but isn't the deploy target — the actual production path is `uvicorn` behind nginx on a single EC2 instance (systemd-managed, see `infra/user_data.sh`).

The reason is the same provider split from above: `embed_query()`/`rerank()` run local PyTorch models in-process on *every* query, regardless of `VYOM_PROVIDER` — Bedrock only replaces generation. That means the deployed process needs ~1-2GB of models loaded into memory, and Lambda would reload them from scratch on every cold start (the interval between requests on a low-traffic app is usually longer than Lambda's warm-container window). An always-on box amortizes that load cost once instead of paying it repeatedly — worth the tradeoff of not being "serverless" for a workload this shaped.

**Running locally on Windows**: plain `uvicorn src.vyom.api.app:app --host 0.0.0.0 --port 8000` hangs forever on every DB query — psycopg's async pool refuses to run on `ProactorEventLoop`, and uvicorn hardcodes exactly that as its Windows default (`uvicorn/loops/asyncio.py`) *unless* `--reload` or `--workers >1` is set (that code path passes `use_subprocess=True`, which picks `SelectorEventLoop` instead). Setting `asyncio.set_event_loop_policy(...)` at import time — the fix already used in every ingest script's `__main__` guard — does **not** work here, because uvicorn calls `asyncio.run(..., loop_factory=self.config.get_loop_factory())`, which constructs the loop directly and ignores the global policy entirely. The practical fix for local dev is just running with `--reload` (which the Windows workaround above happens to trigger as a side effect), or forcing the loop class explicitly:
```
uvicorn src.vyom.api.app:app --host 0.0.0.0 --port 8000 --loop asyncio:SelectorEventLoop
```
This is Windows-only — the EC2 deploy runs Linux, where `ProactorEventLoop` doesn't exist and this never comes up.
