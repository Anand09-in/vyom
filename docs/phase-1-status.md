# Phase 1 — Status

Phase 1 is done. Real data now flows end-to-end: live BSE + RBI sources → Postgres/pgvector → hybrid search, verified against actual retrieval results (not just unit tests).

| What | Status |
|---|---|
| RBI macro data ingest (7 series → narrative chunks) | ✅ |
| BSE annual report ingest (PDF → chunks → embeddings) | ✅ |
| `repo.py` psycopg3 API bugs fixed (5 methods) | ✅ |
| Windows async event-loop fix for the DB pool | ✅ |
| Event-loop-starvation fix (CPU-bound work moved off the loop) | ✅ |
| BSE API response parsing fixed (real schema, not guessed) | ✅ |
| BSE PDF URL reconstruction (two filename eras) | ✅ |
| Local embedding model swapped: BGE-M3 → all-MiniLM-L6-v2 | ✅ |
| Schema migration: `vector(1024)` → `vector(384)` | ✅ |
| Live ingest verified: RBI (65 chunks) + BSE (5 companies, 2,449 chunks) | ✅ |
| Hybrid search (dense + sparse + RRF) verified against real data | ✅ |

## What was built

- **[ingest/rbi.py](../src/vyom/ingest/rbi.py)** — ingests 7 RBI macro series (repo rate, CPI, bank credit growth, forex reserves, INR/USD, IIP, fiscal deficit) from hardcoded recent data (2023-2025; deliberately not scraped live yet — see module docstring). Converts raw `(date, value)` observations into human-readable narrative chunks per quarter plus an overall summary, since raw numbers don't embed usefully.
- **[ingest/bse.py](../src/vyom/ingest/bse.py)** — ingests annual report PDFs for Nifty 50 companies: calls BSE's `AnnualReport` API for a scrip code, downloads the latest PDF, extracts text with `pypdf`, chunks it (512 words / 64 overlap), classifies each chunk into a section (`mda` / `risk_factors` / `financials` / `governance` / `chairman_letter` / `general`) by keyword heuristic, adds a contextual prefix, embeds, and stores.

## Bugs found and fixed

Phase 0 was scaffolded but never actually run against a live database or the real BSE API — so most of Phase 1's work was surfacing and fixing bugs that only show up under real execution, not writing new features. Worth remembering:

1. **Windows event-loop incompatibility** — `psycopg`'s async pool refuses to run on Windows' default `ProactorEventLoop`. Every ingest script's `__main__` block now sets `asyncio.WindowsSelectorEventLoopPolicy()` before `asyncio.run()`. Without this, pool connections fail silently and every operation eventually times out after 30s with no useful error.

2. **`repo.py` was written against the wrong DB driver's API** — several methods used `asyncpg`-style calls that don't exist in `psycopg` 3:
   - `conn.fetchrow(...)` doesn't exist on `psycopg.AsyncConnection` — replaced with `cur = await conn.execute(...); row = await cur.fetchone()` (`upsert_filing`, `upsert_circular`, `log_query`).
   - Query parameters were passed as separate positional arguments (`conn.execute(sql, a, b, c)`) instead of one tuple (`conn.execute(sql, (a, b, c))`) — `psycopg.execute()` takes params as a single sequence (`upsert_rbi_series`).
   - `conn.executemany(...)` doesn't exist on the connection either, only on a cursor — fixed by wrapping in `async with conn.cursor() as cur` (`upsert_rbi_observations`).

3. **Event-loop starvation from synchronous CPU-bound calls** — `provider.embed()` (BGE-M3/MiniLM inference) and PDF text extraction (`pypdf`) are synchronous and CPU-bound. Calling them directly inside `async def` functions blocked the entire event loop for minutes on a full annual report, which starved the async DB pool's own background connection-maintenance tasks until it couldn't hand out connections at all. Fixed by wrapping both in `await asyncio.to_thread(...)` in `bse.py`.

4. **BSE API response schema was guessed wrong** — the original code checked for fields like `PDFURL` / `PDF_URL` / `pdf_url` / `FilePath`, none of which exist. The real response is `{"Table": [{"file_name": "...", "year": "...", "dt_tm": "..."}]}`, newest year first.

5. **`file_name` isn't a URL and needs different reconstruction depending on era** — verified against BSE's live site:
   - Modern filings (~2023+): a UUID with a doubled `.pdf.pdf` suffix (occasionally with a stray leading `\` — a BSE data artifact), served from `https://www.bseindia.com/xml-data/corpfiling/AttachHis/{uuid}.pdf`.
   - Legacy filings: a short numeric filename (e.g. `73256500180.pdf`), served from `https://www.bseindia.com/bseplus/AnnualReport/{scripcode}/{file_name}`.
   - Note: `bseindia.com/AnnualReport/*` is an Angular SPA catch-all that returns `200 text/html` for *any* path including nonexistent ones — a `200` there is not evidence a URL pattern is correct; only `Content-Type: application/pdf` is.

6. **Missing `pypdf` dependency** — used in `bse.py` but never declared; added to `pyproject.toml`.

## Local embedding model: BGE-M3 → all-MiniLM-L6-v2

BGE-M3 (1024-dim) took **~21 minutes** to embed a single annual report (660 chunks) on CPU, even with `torch` saturating 10+ cores. That's ~15-18 hours for the full Nifty 50 sequentially — impractical for iterating on the pipeline.

Switched the local default to **all-MiniLM-L6-v2** (22M params, 384-dim): the same 5-company batch (2,449 chunks total) that would've taken hours completed in **~3.5 minutes**.

This forced a real schema migration, not just a config change — pgvector's `vector(n)` column type enforces its dimension at insert time (`ERROR: expected 1024 dimensions, not 384` if you don't migrate). Changed `vector(1024)` → `vector(384)` in `filing_chunks`, `circular_chunks`, `rbi_chunks` in [schema.sql](../src/vyom/store/schema.sql), matched by `local_embed_model` and `embedding_dim` defaults in [config.py](../src/vyom/config.py) and `.env`/`.env.example`. The old 1024-dim test rows were incompatible and had to be dropped; `filings`/`rbi_series` metadata tables were preserved.

Switching back to BGE-M3 (or to Bedrock's Titan embeddings later) for quality is still just a config change (`VYOM_LOCAL_EMBED_MODEL`), but requires repeating this same schema migration — there's no way to make the vector dimension itself hot-swappable, only the choice of model.

## Verified against live data

- **RBI**: all 7 series ingested — 65 narrative chunks + 65 observations in Postgres, correct 384-dim embeddings.
- **BSE**: 5 Nifty 50 companies ingested (HDFC Bank, Reliance Industries, TCS, Bharti Airtel, ICICI Bank) — 2,449 chunks total, real PDFs downloaded and parsed (1-2 million characters extracted per annual report), correctly section-classified.
- **Hybrid search**: ran `hybrid_search_bse` against real data with the query *"What is HDFC Bank NPA risk in unsecured lending?"* — returned HDFC Bank chunks from `risk_factors` and `financials` sections with sensible RRF scores, confirming the dense (HNSW) + sparse (GIN/tsvector) + RRF fusion pipeline works correctly end-to-end on the new 384-dim schema.

## Known gaps / next steps

- **SEBI ingest doesn't exist yet** — no `ingest/sebi.py`; the `sebi` source has no data behind it.
- **Only 5 of 50 Nifty companies ingested** — the rest of the list is untested; at current speed the full run would take roughly 30-40 minutes.
- **`hybrid_search_sebi` / `hybrid_search_rbi` not live-tested** — only the BSE path and RBI ingest were verified against real data this phase; RBI hybrid search specifically hasn't been queried yet.
- **Company-filtered BSE search (`company=` param) untested** — only the unfiltered path was exercised.
- **DB currently holds only 384-dim embeddings** — switching to BGE-M3 or Bedrock later requires repeating the schema migration described above.
