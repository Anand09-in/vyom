# Phase 0 — Status

Phase 0 is done. Here is what has been built.

| What | Status |
|---|---|
| Project structure | ✅ |
| Virtual environment (`vyom` conda env) | ✅ |
| `pyproject.toml` + deps | ✅ |
| `Provider` interface (local + Bedrock) | ✅ |
| Postgres + pgvector (9 tables, HNSW + GIN indexes) | ✅ |
| Repository with hybrid search SQL | ✅ |
| Chunker with contextual prefix | ✅ |
| Router (BSE / SEBI / RBI / cross) | ✅ |
| LangGraph pipeline (Self-RAG loop) | ✅ |
| FastAPI (8 endpoints, Swagger UI) | ✅ |
| Lambda handler (Mangum) | ✅ |
| 8 unit tests passing | ✅ |
| Eval seed (5 golden Q&A pairs) | ✅ |
| Git committed | ✅ |

## What each piece is, concretely

- **`Provider` interface** — [providers/base.py](../src/vyom/providers/base.py) defines an abstract `embed` / `generate` / `stream` / `rerank` contract. [providers/local.py](../src/vyom/providers/local.py) implements it with BGE-M3 + a local reranker + Ollama ($0 to run). [providers/bedrock.py](../src/vyom/providers/bedrock.py) implements the same contract against Amazon Bedrock (Titan embeddings, Claude via Converse, Bedrock Rerank). [providers/__init__.py](../src/vyom/providers/__init__.py) is the factory — `get_provider()` reads `VYOM_PROVIDER` from settings and returns the right one. Nothing downstream knows or cares which backend is active.

- **Postgres + pgvector** — [store/schema.sql](../src/vyom/store/schema.sql) defines 9 tables across 3 sources (`filings`/`filing_chunks`, `circulars`/`circular_chunks`, `rbi_series`/`rbi_observations`/`rbi_chunks`) plus 2 observability tables (`query_log`, `feedback`). Every chunk table has an HNSW index (dense vector search) and a GIN index over a generated `tsvector` column (BM25-style full-text search).

- **Repository / hybrid search** — [store/repo.py](../src/vyom/store/repo.py) has one hybrid-search method per source. Each runs dense ANN search and sparse full-text search as CTEs in a single query, then merges the two ranked lists with Reciprocal Rank Fusion (RRF) — one round trip, no application-side merging.

- **Chunker** — [ingest/chunker.py](../src/vyom/ingest/chunker.py) splits text into overlapping word-window chunks (`chunk_text`) and prepends a short document-level summary to each chunk (`add_context_prefix`) — contextual retrieval, so a chunk is still meaningful when retrieved in isolation.

- **Router** — [retrieve/router.py](../src/vyom/retrieve/router.py) is a deterministic, regex-based keyword classifier (not an LLM call) that scores a query against BSE/SEBI/RBI signal word lists and decides which source(s) to query, including cross-source detection.

- **LangGraph pipeline** — [retrieve/pipeline.py](../src/vyom/retrieve/pipeline.py) wires `classify_and_rewrite → retrieve_all → grade → generate`, with a conditional edge that loops back to rewrite the query (bounded by `max_rewrite_loops`) if retrieval comes back empty — a corrective Self-RAG pattern.

- **FastAPI** — [api/app.py](../src/vyom/api/app.py) is the app factory (CORS, rate limiting via slowapi, DB pool lifecycle). Routers live under [api/routers/](../src/vyom/api/routers/): `health`, `query` (+ `/query/stream`), `ingest` (`/ingest/bse|sebi|rbi|all`), `feedback` — 8 routes total, all documented at `/docs`.

- **Lambda handler** — [api/lambda_handler.py](../src/vyom/api/lambda_handler.py) wraps the same FastAPI app with Mangum so it runs unchanged on AWS Lambda behind a Function URL.

- **Tests** — [tests/unit/](../tests/unit/) covers config validation, all router scenarios (BSE/SEBI/RBI/cross/fallback), and chunker behavior (windowing, overlap, section labels, context prefix) — no DB or model weights required to run them.

- **Eval seed** — [eval/golden.jsonl](../eval/golden.jsonl) has 5 hand-written Q&A pairs spanning single-source and cross-source questions, used by [eval/run_ragas.py](../eval/run_ragas.py) for RAGAS scoring.

## Not yet built (later phases)

- `ingest/` source clients (BSE/SEBI/RBI scrapers) — only the chunker exists so far
- `mcp/server.py` — stub, no tools implemented yet
- `frontend/` — directory scaffolding only
- `infra/main.tf` — stub, no Terraform resources defined
- `.github/workflows/ci.yml` — stub, no CI pipeline defined
- Live DB — schema is written but Postgres hasn't been started via `docker compose up -d db` yet
