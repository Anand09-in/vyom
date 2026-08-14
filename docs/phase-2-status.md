# Phase 2 — Status

Phase 2 is done. Full corpus ingested, SEBI added, RAGAS+MLflow eval harness built, and the provider architecture reworked into a hybrid split: generation on Bedrock, embedding and reranking always local.

| What | Status |
|---|---|
| SEBI circular ingest (`ingest/sebi.py`) | ✅ |
| Full Nifty 50 BSE ingest (50 companies) | ✅ |
| Local embedding model swapped: MiniLM → nomic-embed-text-v1.5 | ✅ |
| Schema migration: `vector(384)` → `vector(512)` | ✅ |
| GPU acceleration for local embed/rerank + memory-leak fix | ✅ |
| Duplicate `filings` row bug fixed (real `dt_tm` filing date) | ✅ |
| RAGAS + MLflow eval harness (`eval/run_ragas.py`) | ✅ |
| Judge model selection (Ollama vs. Bedrock, throttling/billing fixes) | ✅ |
| Provider architecture split: generation → Bedrock, embed/rerank → always local | ✅ |
| GPU contention (Ollama vs. local models) diagnosed and eliminated | ✅ |
| Full 20-question RAGAS baseline on the new architecture | ✅ |

## What was built

- **[ingest/sebi.py](../src/vyom/ingest/sebi.py)** — ingests SEBI regulatory circulars, following the same shape as `bse.py`/`rbi.py`: fetch → chunk → context-prefix → embed → upsert.
- **[eval/run_ragas.py](../eval/run_ragas.py)** — runs the golden question set through the real pipeline (not mocked), scores the results with [RAGAS](https://github.com/explodinggradients/ragas) (`faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`), logs metrics to MLflow, and fails CI loudly if `faithfulness` is `NaN` or below threshold. The judge LLM is switchable (`VYOM_RAGAS_JUDGE_PROVIDER=local|bedrock`) and deliberately a third model family, distinct from both the local dev model and the production generation model, to avoid self-evaluation bias.
- **Reworked [providers/bedrock.py](../src/vyom/providers/bedrock.py)** — no longer calls Bedrock's Titan embed or Rerank APIs. `embed()`/`embed_query()`/`rerank()` delegate to an internally-constructed `LocalProvider`; only `generate()`/`stream()` are real Bedrock Converse API calls.

## Embedding model: MiniLM → nomic-embed-text-v1.5

Phase 1 picked MiniLM (384-dim) purely for ingest speed. Revisited for quality once ingest speed was no longer the bottleneck (GPU acceleration, below):

- **Nomic embed-text-v1.5**: 137M params, 8192-token context (MiniLM's 256-token limit was silently truncating our 512-word chunks), higher MTEB retrieval score than both MiniLM and Bedrock Titan v2 on English text.
- **Matryoshka Representation Learning** — Nomic natively supports truncating its 768-dim output down to any smaller size (down to 64) via a `truncate_dim` parameter, with minimal quality loss. This is what makes `embedding_dim` a config knob instead of a retrain: picked **512** as a "standard" middle ground between 384 (Phase 1) and the native 768.
- **Asymmetric query/document embedding** — Nomic requires different prefixes for indexed content vs. queries: `"search_document: "` for chunks, `"search_query: "` for queries. Same model and weights, trained to map both into complementary regions of one shared space — deliberately *not* the same as using two different models for query vs. document, which would produce mathematically incompatible vector spaces even at matching dimensions. `LocalProvider.embed()` uses the document prefix; the new `embed_query()` override uses the query prefix (previously inherited a base-class default that would have wrongly reused the document prefix for queries).
- **Required another schema migration** — `vector(n)` enforces its dimension at insert time, and switching models (even to the same output size) produces an incompatible vector space regardless — so `vector(384)` → `vector(512)` in `filing_chunks`/`circular_chunks`/`rbi_chunks` required dropping and re-inserting all existing rows, not just a column-type change.

## GPU acceleration and a memory leak

Full Nifty 50 ingestion on CPU was projected at many hours based on Phase 1's per-company timing. Moved embedding/reranking to GPU (`torch` CUDA build), which surfaced two distinct problems in sequence, both now fixed in [providers/local.py](../src/vyom/providers/local.py):

1. **GPU memory leak** — `torch`'s CUDA allocator caches freed memory for reuse rather than returning it to the OS. Across thousands of small `.encode()`/`.predict()` calls in one long-running ingest process, cached-but-unused memory accumulated until 6GB VRAM was exhausted, causing catastrophic (100-300x) slowdowns from allocation contention/fragmentation — not a crash, just silently getting slower and slower. Fixed by calling `torch.cuda.empty_cache()` after every `embed()`, `embed_query()`, and `rerank()` call; verified flat memory usage across a 40-batch stress test.
2. **GPU contention between concurrently-loaded models** (discovered later, during eval — see below) — a distinct issue from the memory leak, caused by an incomplete provider migration, not a bug in the embedding code itself.

## Duplicate filing rows

Re-ingesting the same company on a different calendar day created a *new* `filings` row instead of updating the existing one, because `filing_date` was being set to `date.today()` rather than the filing's real date — so the uniqueness constraint (keyed on `filing_date`) never matched across re-runs. Fixed by extracting BSE's actual `dt_tm` field from the API response as the true filing date. Five pre-existing orphaned duplicates were cleaned up directly in Postgres.

## Full ingestion, verified

| Table | Count |
|---|---|
| `filings` | 50 (all Nifty 50 companies) |
| `filing_chunks` | 25,867 |
| `circulars` | 10 |
| `circular_chunks` | 10 |
| `rbi_series` | 7 |
| `rbi_observations` | 79 |
| `rbi_chunks` | 65 |

Spot-checked retrieval quality across the full corpus via direct `hybrid_search_*` calls and live `/query` API requests, including cross-source queries spanning SEBI + RBI.

## RAGAS judge model: five swaps, three real blockers

Getting a reliable RAGAS judge running was the longest debugging arc of this phase, driven by real failures rather than anticipated ones:

1. **RAGAS's default `max_workers=16`** overwhelmed both a CPU-bound local Ollama model (`TimeoutError`) and an AWS Bedrock on-demand quota (`ThrottlingException`, even at `max_workers=2`) — reduced to `max_workers=1`, i.e. fully serial judge calls, which even a 100 RPM model needed due to per-job internal sub-call concurrency.
2. **Bedrock inference profiles** — some model families (Claude 3.5 Sonnet, Amazon Nova) reject the bare model ID for on-demand invocation (`ValidationException: ... use an inference profile`) and require a region-prefixed profile ID instead (e.g. `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`).
3. **AWS Marketplace billing gate** — Anthropic models on Bedrock need a separate AWS Marketplace subscription with a valid payment instrument, distinct from IAM permissions or the Bedrock console's model-access toggle. This account hit `INVALID_PAYMENT_INSTRUMENT`, which isn't fixable in code — Claude was abandoned entirely as a candidate, for both the judge and (later) the app's own generation model.
4. **`langchain_aws.ChatBedrock` vs. `ChatBedrockConverse`** — the older `ChatBedrock` class's DeepSeek payload builder is broken (`ValidationException: missing field 'messages'`); switched to `ChatBedrockConverse`, which uses the unified modern Converse API and works correctly across model families.
5. **Llama 3 70B rejected** for the app's own generation model specifically for its ~4 RPM quota — too low for practical use. Settled on **Mistral Large 3** (100 RPM / 100M TPM, works on-demand, no inference profile needed) for generation, and **DeepSeek V3.2** for the RAGAS judge — three distinct model families across dev-Ollama / prod-generation / eval-judge, deliberately, to avoid self-evaluation bias.

## Provider architecture: generation → Bedrock, embed/rerank → always local

The `--questions 5` eval run surfaced severe reranker slowdown (70-96s vs. a normal ~1.6s) that turned out to be a second, distinct GPU issue from the earlier memory leak: Ollama auto-loads its model onto the GPU whenever a CUDA device is present, independent of the Python process's own device selection. With Ollama's `qwen2.5:3b`, the local embedder, and the local reranker all competing for the same 6GB card, none of them ran well.

Root cause: the "generation should move to Bedrock" decision had been made and applied to the RAGAS judge, but never actually completed for the main app — `VYOM_PROVIDER` was still `local`, so the app was still calling Ollama for every generation. Fixing this required more than flipping the env var, since the existing `BedrockProvider` called Bedrock's Titan embed API and (blocked) Rerank API — neither of which was ever the intent. Reworked so:

- `BedrockProvider.generate()` / `.stream()` — real Bedrock Converse API calls (Mistral Large 3). Models needed for generation are too large to run locally.
- `BedrockProvider.embed()` / `.embed_query()` / `.rerank()` — delegate to an internally-constructed `LocalProvider`. Embedding and reranking are cheap and fast on local CPU/GPU with no per-call cost or quota; Bedrock's Titan `embed()` also calls `invoke_model` once per text with no batching (a real bottleneck at ingest volume), and Bedrock's Rerank API was separately blocked by an IAM permissions gap (`AccessDeniedException`) — never fixed, since the architectural answer (always local) made the IAM gap moot.

So `VYOM_PROVIDER=bedrock` does **not** mean "everything via AWS" — it means "generation via Bedrock, embedding and reranking via local models," documented directly in the module docstrings for `config.py` and `providers/bedrock.py` so it isn't rediscovered as a surprise later.

Verified end-to-end through the real `get_provider()` factory after the change:

```
embed_query: 512-dim in 20.30s   (includes one-time model load)
rerank: 2 results in 9.55s        (includes one-time model load; correctly
                                    scored the query-relevant document far
                                    higher than the unrelated one)
generate (Bedrock/Mistral): 0.53s -> '"Hey there!"'
```

And confirmed the GPU contention was actually gone, not just faster: `ollama ps` returned empty (Ollama no longer holds any model on the GPU at all, since generation never calls it anymore), GPU utilization dropped to ~3% idle / ~1.9GB used (just the embedder + reranker), and a rerank benchmark that had degraded to 70-96s during the contention period was back to **0.25s** warm.

## Full RAGAS baseline (post-migration)

Ran the full 20-question golden set against the completed architecture (Bedrock generation, local embed/rerank, DeepSeek judge, full 50-company corpus):

| Metric | Score | Phase 1 baseline (local qwen2.5:3b generation) |
|---|---|---|
| Faithfulness | **0.7817** | 0.6132 |
| Answer relevancy | 0.7922 | — |
| Context precision | 0.3465 | — |
| Context recall | 0.3859 | — |

Faithfulness and answer relevancy are strong and clearly improved by the move to Bedrock generation. Context precision/recall are low, which points at the **retrieval side** (hybrid search / reranking bringing back too many irrelevant chunks, or missing relevant ones) rather than generation — flagged as a concrete next-step candidate rather than fixed in this phase.

## Known gaps / next steps

- **Context precision/recall (0.35, 0.39) are the weakest metrics** — worth investigating hybrid search / RRF tuning, `top_k`/`rerank_top_n` values, or chunking strategy before the next eval round.
- **`tests/unit/test_config.py::test_defaults`** asserts `provider == "local"`, but `Settings()` reads `.env` by design — this now fails locally (where `.env` legitimately sets `VYOM_PROVIDER=bedrock`) even though it still passes in CI (no `.env` in a fresh clone). Not fixed this phase since it's a test-isolation design call, not a functional bug.
- **`conda run` on Windows garbles/crashes on non-ASCII console output** (`cp1252` `UnicodeEncodeError`) when forwarding a subprocess's buffered stdout — harmless to the underlying script (which completes and writes its output normally), but means `conda run`'s own final console print can't be trusted as a completion signal. Prefer invoking the env's `python.exe` directly for future long-running scripts.
- **AWS credential exposure** — a `cat ~/.aws/credentials` earlier in this project's history printed real AWS access key/secret to a terminal transcript. Flagged for rotation; not something this phase's work could fix in code.
