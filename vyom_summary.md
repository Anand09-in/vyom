# Vyom — Project Summary & Development Phases

**Builder:** Anand Kumar Sahu
**Role target:** ML Engineer (India)
**Status:** Architecture complete, Phase 0 scaffold built, ready for Phase 1

---

## What Vyom is

Vyom is a **production-grade, multi-source agentic RAG system** that answers
questions about Indian listed companies by grounding every response in three
public data sources simultaneously — BSE/NSE corporate filings, SEBI regulatory
circulars, and RBI macroeconomic data — with citations back to the exact source
document.

The name Vyom (व्योम) means sky in Sanskrit — a fixed vantage point that sees
across all sources at once.

---

## The problem it solves

An analyst trying to assess HDFC Bank's credit risk today has to manually
cross-reference three completely disconnected sources: the bank's annual report
on BSE, RBI's latest circular on NBFC lending norms, and the Reserve Bank's
current repo rate and credit growth data. No tool synthesizes these. Vyom does.

**The signature question no single-source RAG can answer:**

> "HDFC Bank's annual report flags rising NPA risk in unsecured lending — what
> does RBI's latest monetary policy say about repo rate direction, and has SEBI
> issued any recent circulars tightening NBFC co-lending norms?"

---

## Why it exists (the honest reason)

This is a portfolio project for a 1-YOE developer who has been job-hunting for
7 months, targeting ML Engineer roles in India. The goal is one deployed,
measured, defensible system that can be re-framed for three different role types
from the same codebase:

- **ML Engineer** — retrieval pipeline, hybrid search, reranking, LangGraph
  agentic loop, RAGAS eval CI gate, Bedrock serving, latency numbers
- **Data Engineer** — three ingestion pipelines, normalized Postgres schema,
  S3 raw zone, EventBridge scheduled re-indexing, idempotent upserts
- **Data Scientist** — golden Q&A evaluation set, controlled experiment
  (dense vs hybrid vs reranked), metric deltas logged in MLflow

---

## Data sources

| Source | What it holds | Access method |
|---|---|---|
| **BSE / NSE** | Annual reports, quarterly results, corporate announcements for Nifty 50 companies | `pip install bse` — free community wrapper |
| **SEBI** | Regulatory circulars, enforcement orders, BRSR/ESG mandates | PDF scraper on sebi.gov.in — public, no auth |
| **RBI DBIE** | Repo rate, CPI, credit growth, IIP, forex reserves — 14 macro series | Scheduled CSV download — official RBI publication |

**Why not USPTO (the original plan):** USPTO ODP required ID.me US identity
verification as of June 2026 — blocked for non-US citizens. SEBI fills the
regulatory source role and is more relevant to Indian hiring managers anyway.

---

## Architecture in one paragraph

A query enters the FastAPI endpoint on AWS Lambda (outside VPC, no NAT Gateway).
A rule-based keyword router classifies it as a BSE filing question, a SEBI
regulatory question, an RBI macro question, or a cross-source question requiring
all three. The LangGraph pipeline embeds the query with HyDE expansion, fans
out to the relevant Postgres tables (hybrid HNSW + BM25 search, fused with
Reciprocal Rank Fusion), reranks the top candidates with a cross-encoder, and
grades the result. If relevance is low it rewrites and retries (Self-RAG loop,
max 2 iterations). The generator produces a cited answer tagged `[BSE:id]`,
`[SEBI:id]`, `[RBI:id]`, which streams over SSE to the Next.js frontend.
Every query is logged. Thumbs-down responses feed back into the golden eval set.

---

## Agentic patterns used

**Pattern 1 — Orchestrator / router:** A coordinator node dispatches to
worker retrievers (BSE, SEBI, RBI) based on keyword signals. Rule-based, not
LLM-based — faster, cheaper, and deterministic for a finite financial vocabulary.

**Pattern 2 — Self-RAG corrective loop:** After retrieval, a grade node
checks relevance. If chunks are weak it loops back to rewrite and retry (max 2
loops). Control flow is a fixed LangGraph graph — not free-form ReAct. The
model never picks its own next action; the graph decides.

---

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.2+ |
| API | FastAPI + Mangum (Lambda adapter) |
| Database | PostgreSQL 16 + pgvector |
| Vector index | HNSW cosine (pgvector) |
| Text index | GIN tsvector (BM25) |
| Hybrid fusion | Reciprocal Rank Fusion (SQL CTE) |
| Embeddings (local) | BGE-M3 via sentence-transformers |
| Reranker (local) | bge-reranker-v2-m3 CrossEncoder |
| Generation (local) | Ollama — qwen2.5:7b |
| Embeddings (cloud) | Amazon Bedrock Titan v2 |
| Generation (cloud) | Amazon Bedrock Claude 3.5 Sonnet |
| Reranker (cloud) | Amazon Bedrock Rerank |
| Evaluation | RAGAS (faithfulness · relevancy · precision · recall) |
| Experiment tracking | MLflow |
| Frontend | Next.js 15 · React 18 · TypeScript · Tailwind CSS |
| IaC | Terraform |
| CI/CD | GitHub Actions |
| Deploy | AWS Lambda + Function URL + RDS + S3 + ECR |
| MCP | stdio MCP server (4 tools for Claude Desktop) |

---

## What is NOT in v1 (deliberate scope cuts)

- No fine-tuning in v1 — RAG solves the knowledge problem; behaviour is
  handled by system prompt + guardrails. Fine-tuning the embedding model
  (domain-adaptive QLoRA on hard negatives) is Phase 5+ after real eval data exists.
- No Neo4j graph route — cross-company entity relationships are a v2 stretch.
- No real-time market data — Vyom is a research tool, not a trading tool.
- No authentication — single shared demo instance.
- No text-to-SQL over XBRL structured financials — deferred to stretch.

---

## Development phases

### Phase 0 — Foundations ✅ Complete
*Goal: a runnable, tested repo skeleton before writing domain logic.*

- Repo structure created (`src/sec_rag/`, providers, ingest, store, retrieve, api, mcp)
- `pyproject.toml` with uv, ruff, pytest; `.env.example`; `docker-compose.yml`
- `Provider` abstract interface with `LocalProvider` (BGE-M3 + Ollama) and
  `BedrockProvider` (Titan + Claude + Bedrock Rerank) — one env var switches them
- `docker-compose.yml` with `pgvector/pgvector:pg16` + MLflow
- Postgres schema: all 8 tables with HNSW + GIN indexes
- `Repository` class with hybrid search SQL for all three sources
- FastAPI app, routers (query, ingest, feedback, health), Mangum Lambda handler
- MCP server with 4 tools
- Next.js frontend with SSE streaming, citation badges, feedback buttons
- Terraform infra (Lambda, RDS, S3, ECR, EventBridge, Budget alarm at $50)
- GitHub Actions CI workflow (lint → test → RAGAS gate → Terraform apply)
- **26 unit tests passing, ruff clean**

**Done when:** `make test` passes. ✅

---

### Phase 1 — Ingestion and data layer
*Goal: real Indian fintech data flowing into pgvector.*

**BSE ingestion (`ingest/bse.py`)**
- Use `pip install bse` community wrapper to pull Nifty 50 scrip codes
- Download annual report PDFs from BSE corporate filings endpoint
- Parse PDFs with Docling (handles scanned PDFs, tables, multi-column layouts)
- Extract key sections: MD&A, risk factors, financial highlights, notes to accounts
- Chunk (512 words, 64 overlap) + contextual retrieval prefix
- Embed with BGE-M3 → upsert into `filings` + `filing_chunks`
- Store raw PDFs in S3 (`filings/{company}/{year}/annual_report.pdf`)

**RBI DBIE ingestion (`ingest/rbi.py`)**
- Download 14 macro series as CSV from fixed DBIE publication URLs
- Parse with pandas → upsert raw observations into `rbi_observations`
- Build narrative text chunks per quarter:
  "Repo rate held at 6.5% for Q3-2025, third consecutive unchanged MPC meeting"
- Embed narratives → upsert into `rbi_chunks`
- Also download and chunk RBI monetary policy statements (PDF)

**Companies: Nifty 50**
```
RELIANCE  TCS       HDFCBANK  BHARTIARTL  ICICIBANK
INFY      SBIN      HINDUNILVR LT         ITC
KOTAKBANK BAJFINANCE HCLTECH   WIPRO       AXISBANK
ASIANPAINT MARUTI   SUNPHARMA  TITAN       ULTRACEMCO
POWERGRID  NTPC     BAJAJFINSV TECHM       NESTLEIND
ONGC      TATAMOTORS ADANIENT  JSWSTEEL    COALINDIA
DRREDDY   DIVISLAB  HINDALCO   CIPLA       BPCL
TATACONSUM EICHERMOT M&M       APOLLOHOSP  GRASIM
INDUSINDBK BRITANNIA HEROMOTOCO SBILIFE    BEL
TRENT     BAJAJ-AUTO SHRIRAMFIN ADANIPORTS  HDFCLIFE
```

**Done when:** `SELECT company_name, COUNT(*) FROM filing_chunks GROUP BY company_name`
shows all 50 companies with sane chunk counts.

---

### Phase 2 — Baseline and eval harness (build this BEFORE optimising)
*Goal: a measurable baseline. Numbers first, optimisation second.*

**Golden evaluation set (`eval/golden.jsonl`)**
Write 50 questions, hand-verify every answer against the actual source document.
Structure: `{"question": "...", "answer": "...", "company": "HDFCBANK", "sources": ["bse"]}`

Seed categories:
- 15 BSE-only filing questions (NPA levels, revenue segments, capex plans)
- 10 RBI-only macro questions (repo rate history, credit growth, IIP)
- 10 SEBI-only regulatory questions (BRSR mandates, NBFC norms, enforcement orders)
- 15 cross-source questions (company risk + regulatory context + macro backdrop)

**Baseline pipeline**
- Dense-only pgvector search → stuff top-k → generate
- Run `eval/run_ragas.py` → record faithfulness, answer_relevancy,
  context_precision, context_recall
- Log to MLflow experiment `vyom-baseline`
- Write baseline numbers into README metrics table

**Done when:** `make eval` produces a reproducible metrics table.
Faithfulness baseline is typically 0.55–0.70 for naive dense-only RAG.

---

### Phase 3 — SEBI ingestion + retrieval quality
*Goal: all three sources live; headline metric improvement.*

**SEBI ingestion (`ingest/sebi.py`)**
- Scrape circulars listing page at sebi.gov.in/sebiweb/home/HomeAction.do
- Download new PDFs (filter by date, deduplicate by circular number)
- Classify category: `NBFC | BRSR | enforcement | market_conduct | other`
- Chunk and embed → upsert into `circulars` + `circular_chunks`
- Treat SEBI scraper as a spike first run — validate output quality before
  treating it as reliable (most fragile of the three sources)

**Router retraining**
- Replace US signal lists (10-K, MD&A, CPI) with Indian vocabulary:
  NPA, GNPA, NNPA, NIM, NBFC, co-lending, repo rate, CRR, SLR,
  BRSR, ESG, Nifty, Sensex, SEBI circular, RBI directive, MPC,
  forex, INR, UPI, NACH, credit offtake, IIP
- Add cross-source trigger patterns specific to Indian fintech

**Retrieval improvement**
- Add hybrid BM25 + dense to all three source branches (already wired, needs tuning)
- Tune RRF `k` constant per source (filing chunks vs regulatory text vs macro narratives
  have different length and density profiles)
- Rerun eval → record delta vs baseline
- Target: faithfulness ≥ 0.75 (CI gate threshold)

**Done when:** `make eval` passes the CI gate (faithfulness ≥ 0.75) and
hybrid + rerank shows measurable improvement over baseline in README.

---

### Phase 4 — Deploy → MVP ship point
*Goal: a live URL anyone can hit. Start applying after this phase.*

**Bedrock flip**
- Set `SEC_RAG_PROVIDER=bedrock` in Lambda environment
- Re-embed all chunks via Bedrock Titan v2 (same 1024-dim as BGE-M3 — no
  schema migration needed, this was a deliberate design decision)
- Load production embeddings into RDS

**Terraform apply**
```
infra/main.tf provisions:
  - ECR repo + Lambda (query + ingest) + Function URL
  - RDS db.t4g.micro (publicly accessible, SG-locked, TLS)
  - S3 bucket (raw PDFs + static frontend)
  - EventBridge rule (weekly Sunday 02:00 UTC)
  - IAM role (Bedrock + S3 permissions)
  - Budget alarm ($50 threshold, email at 80%)
```

**Frontend deploy**
- Build Next.js → `next export` → upload to S3 → serve as static site
- Set `NEXT_PUBLIC_API_URL` to Lambda Function URL

**Record demo video (permanent artifact)**
- 30–60 second screen recording showing a cross-source query
- Best demo query: HDFC Bank NPA risk + RBI rate direction + SEBI NBFC norms
- Upload to YouTube or Loom, embed in README
- This video outlasts the live URL (AWS credits expire in 6 months)

**Update resume and LinkedIn** — do this the day the live URL works.
Do not wait for Phase 5.

**Done when:** a stranger hits the URL and gets a cited cross-source answer.

---

### Phase 5 — MLOps loop (post-ship, while applying)
*Each item below is one additional resume bullet. Pick based on which role
you're interviewing for that week.*

**5a — CI eval gate (all roles)**
- GitHub Actions runs `pytest` + RAGAS on every PR to `main`
- Merge blocked if faithfulness drops below 0.75
- Eval results uploaded as Actions artifact
- Implement this first — it's the clearest "I understand ML systems" signal

**5b — Observability (ML Engineer)**
- Add Langfuse tracing: per-span latency (embed, retrieve, rerank, generate),
  token cost per query, retrieval quality scores
- Build a simple dashboard: avg faithfulness over time, p95 latency,
  cost per query, top failing query patterns
- Resume bullet: "instrumented end-to-end RAG tracing with Langfuse,
  identified retrieval as the dominant latency contributor at p95"

**5c — Feedback loop (ML Engineer + Data Scientist)**
- Thumbs-down queries auto-exported to `eval/failing_queries.jsonl`
- Weekly review: promote good failures to `golden.jsonl` (new test cases)
- This is what turns the eval set from 50 static questions into a living
  quality signal that improves with usage

**5d — dbt + Dagster (Data Engineer)**
- Add dbt models over XBRL structured financials (revenue, margins, EPS)
  parsed from BSE filing XML attachments
- Dagster orchestrates: ingest → dbt transform → embed → eval
- Data quality tests: expect_column_values_to_not_be_null on key fields
- Resume bullet: "built dbt financial data marts with Dagster orchestration
  and data quality gates, enabling structured financial queries alongside
  unstructured RAG retrieval"

**5e — Embedding fine-tune (Data Scientist / ML Engineer)**
- Mine hard negative pairs from production query_log (queries where grade
  looped and relevance was low)
- QLoRA fine-tune BGE-M3 on those pairs using sentence-transformers + PEFT
  on Kaggle free GPU (~30 GPU-hours/week)
- Re-embed all chunks with the fine-tuned model
- Measure context_precision delta on golden set → log to MLflow
- Resume bullet: "domain-adaptive QLoRA fine-tune of BGE-M3 on Indian
  fintech hard negatives, lifting context_precision from X to Y"

**5f — MCP server update (ML Engineer)**
- Update MCP tool names and descriptions from SEC/USPTO/FRED to BSE/SEBI/RBI
- Add a `cross_source_query` tool for Claude Desktop
- Demo: connect Claude Desktop to Vyom, show it pulling BSE + SEBI + RBI
  to answer a company-specific regulatory question
- Record a 60-second MCP demo video — very high visual impact

---

## Three resume bullets (fill in your numbers after Phase 3)

**ML Engineer**
> Built Vyom, a multi-source agentic RAG system (LangGraph, pgvector,
> Amazon Bedrock) routing queries across BSE filings, SEBI circulars, and
> RBI macro data; improved faithfulness from X→Y on a 50-question Indian
> fintech eval set using hybrid retrieval + cross-encoder reranking, with
> a RAGAS CI gate blocking regressions.

**Data Engineer**
> Designed and built three production ingestion pipelines (BSE annual
> reports, SEBI PDF circulars, RBI DBIE macro CSVs) into Postgres/pgvector
> with idempotent upserts, S3 raw zone, and weekly EventBridge-triggered
> re-indexing — all provisioned with Terraform on AWS.

**Data Scientist**
> Designed a 50-question golden evaluation set for an Indian fintech RAG
> system, ran controlled retrieval experiments (dense-only vs hybrid vs
> reranked) with RAGAS metrics logged in MLflow, achieving faithfulness
> of Y and identifying the primary failure mode as [what you found].

---

## Timeline estimate

| Phase | Work | Elapsed |
|---|---|---|
| 0 | Foundations | ✅ Done |
| 1 | BSE + RBI ingest | Weekend 1–2 |
| 2 | Eval harness + baseline | Weekend 2–3 |
| 3 | SEBI + retrieval tuning | Weekend 3–4 |
| 4 | Deploy + demo video | Weekend 4–5 |
| 5+ | Stretches (ongoing) | While applying |

**Total to MVP: 4–5 focused weekends.**
Start applying after Phase 4. Do not wait for Phase 5.

---

## Key decisions recorded

| Decision | Choice | Reason |
|---|---|---|
| Domain pivot | Fintech (BSE+SEBI+RBI) over US sources | USPTO access blocked for non-US citizens; Indian domain more relevant for Indian ML roles |
| Router type | Rule-based keyword, not LLM-based | Financial vocabulary is finite; saves latency + Bedrock tokens on every query |
| Agentic pattern | Orchestrator + Self-RAG corrective loop | Not ReAct — fixed graph gives deterministic control flow, no runaway loops |
| No VPC on Lambda | Lambda outside VPC | Avoids NAT Gateway ($33/mo = 33% of total credit budget) |
| One Postgres for everything | pgvector + tsvector in RDS | Avoids separate vector DB cost; hybrid search in one SQL round-trip |
| Narrative chunks for RBI | Convert numbers to text before embedding | "Repo rate 6.5%" doesn't embed usefully; "held for third consecutive meeting, signals pause" does |
| Fine-tuning deferred to Phase 5 | No fine-tune in v1 | RAG solves knowledge; system prompt + guardrails solve behaviour; fine-tune only when eval data exists |
| Faithfulness gate at 0.75 | Hard CI gate, not a soft target | Fabricated financial claims are worse than slow responses — priority encoded in pipeline |
| SEBI deferred to Phase 3 | BSE + RBI first | SEBI PDF scraper is most fragile; sequence by reliability |
| Demo video as permanent artifact | Record 30–60s video | Live URL expires when credits run out; video is permanent |