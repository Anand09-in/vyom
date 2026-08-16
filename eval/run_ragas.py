"""Vyom RAGAS evaluation harness.

Runs the full pipeline on every question in golden.jsonl and measures:
  - faithfulness:       are claims in the answer supported by retrieved context?
  - answer_relevancy:   does the answer address the question?
  - context_precision:  are retrieved chunks actually relevant?
  - context_recall:     did we retrieve enough relevant chunks?

Results are printed to stdout AND logged to MLflow so every run is versioned.

CI gate: exits with code 1 if faithfulness < FAITHFULNESS_THRESHOLD.
This blocks GitHub Actions deploy when retrieval quality degrades.

Usage:
  python eval/run_ragas.py
  python eval/run_ragas.py --golden eval/golden.jsonl --out eval/results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
FAITHFULNESS_THRESHOLD = 0.50   # Start at 0.50 for baseline; raise to 0.75 in Phase 3


# ── Pipeline runner ────────────────────────────────────────────────────────────

async def _run_pipeline_on_question(
    question: str,
    company: str | None,
    sources: list[str],
    pipeline,
    repo,
) -> dict:
    """Run one golden question through the Vyom pipeline and return the result."""
    from vyom.retrieve.pipeline import VyomState
    from vyom.retrieve.router import route

    enabled = sources if sources else ["bse", "sebi", "rbi", "cross"]
    decision = route(question, enabled)

    initial = VyomState(
        query=question,
        rewritten_query=question,
        company=company,
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

    result = await pipeline.ainvoke(initial)
    return result


async def _run_conversation_through_pipeline(
    turns: list[dict],
    company: str | None,
    sources: list[str],
    pipeline,
) -> list[dict]:
    """
    Run a multi-turn conversation through the pipeline sequentially,
    exercising the same history_recent-driven query condensation that
    /query and /query/stream use for real follow-up questions (see
    classify_and_rewrite in pipeline.py).

    Deliberately in-memory only: history_recent is built up locally from
    each turn's ACTUAL pipeline answer (not the golden ground truth,
    matching what happens in production), and never touches HistoryStore
    or Redis — eval runs must not pollute the real conversation history
    or show up in the sidebar's "recent conversations" list.

    Returns one flat record per turn (same shape as single-turn records),
    so a conversation's turns each contribute independently to the RAGAS
    dataset — the interesting signal is on follow-up turns specifically,
    where a correct score means the pipeline actually resolved the
    conversational reference (pronouns, implicit company/topic) rather
    than just answering the raw text in isolation.
    """
    from vyom.retrieve.pipeline import VyomState
    from vyom.retrieve.router import route

    enabled = sources if sources else ["bse", "sebi", "rbi", "cross"]
    history_recent: list[dict] = []
    records: list[dict] = []

    for turn in turns:
        question = turn["question"]
        ground_truth = turn["answer"]
        decision = route(question, enabled)

        initial = VyomState(
            query=question,
            standalone_query=question,
            rewritten_query=question,
            company=company,
            history_recent=list(history_recent),
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

        try:
            result = await pipeline.ainvoke(initial)
            answer = result.get("answer", "")
            contexts = (
                [c.content for c in result.get("filing_chunks", [])]
                + [c.content for c in result.get("circular_chunks", [])]
                + [c.content for c in result.get("rbi_chunks", [])]
            )
        except Exception as exc:
            logger.error("Pipeline error on multi-turn question %r: %s", question, exc)
            answer = "Error: pipeline failed."
            contexts = ["No context retrieved."]

        records.append({
            "question":     question,
            "answer":       answer,
            "contexts":     contexts if contexts else ["No context retrieved."],
            "ground_truth": ground_truth,
        })

        # Feed the real answer forward, not the ground truth — history_recent
        # in production is built from what the model actually said.
        history_recent.append({"question": question, "answer": answer})

    return records


async def _build_eval_dataset(
    golden: list[dict],
    settings,
    golden_multiturn: list[dict] | None = None,
) -> list[dict]:
    """
    Run every golden question (and, if given, every multi-turn conversation)
    through the pipeline. Returns a flat list of dicts with question,
    answer, contexts, ground_truth — one per single-turn question or per
    conversation turn.
    """
    from vyom.store.repo import create_pool, Repository
    from vyom.providers import get_provider
    from vyom.retrieve.pipeline import build_pipeline

    provider = get_provider(settings)
    pool     = await create_pool(settings)
    await pool.open()
    repo     = Repository(pool)
    pipeline = build_pipeline(
        provider=provider,
        repo=repo,
        top_k=settings.top_k,
        rerank_top_n=settings.rerank_top_n,
        max_loops=settings.max_rewrite_loops,
    )

    records: list[dict] = []

    for i, item in enumerate(golden):
        question   = item["question"]
        ground_truth = item["answer"]
        company    = item.get("company")
        sources    = item.get("sources", [])

        logger.info("[%d/%d] %s", i + 1, len(golden), question[:80])

        try:
            result = await _run_pipeline_on_question(
                question=question,
                company=company,
                sources=sources,
                pipeline=pipeline,
                repo=repo,
            )

            answer   = result.get("answer", "")
            contexts = (
                [c.content for c in result.get("filing_chunks", [])]
                + [c.content for c in result.get("circular_chunks", [])]
                + [c.content for c in result.get("rbi_chunks", [])]
            )

            records.append({
                "question":     question,
                "answer":       answer,
                "contexts":     contexts if contexts else ["No context retrieved."],
                "ground_truth": ground_truth,
            })

        except Exception as exc:
            logger.error("Pipeline error on question %d: %s", i + 1, exc)
            records.append({
                "question":     question,
                "answer":       "Error: pipeline failed.",
                "contexts":     ["No context retrieved."],
                "ground_truth": ground_truth,
            })

    for i, convo in enumerate(golden_multiturn or []):
        turns   = convo["turns"]
        company = convo.get("company")
        sources = convo.get("sources", [])

        logger.info(
            "[multi-turn %d/%d] %d turns, starting: %s",
            i + 1, len(golden_multiturn), len(turns), turns[0]["question"][:60],
        )
        records.extend(
            await _run_conversation_through_pipeline(turns, company, sources, pipeline)
        )

    await pool.close()
    return records


# ── RAGAS evaluation ───────────────────────────────────────────────────────────

def _build_ragas_judge(settings):
    """
    Build the LLM + embeddings RAGAS uses to judge faithfulness/answer_relevancy.

    Controlled by ragas_judge_provider, independent of the app's own
    VYOM_PROVIDER — retrieval/ingest can stay on the local embedding setup
    (whose 384-dim schema is already populated) while the judge alone uses
    Bedrock, since RAGAS's structured JSON output prompts and concurrent
    judge calls are unreliable against a CPU-bound local Ollama model. No
    OpenAI dependency or API key required either way.
    """
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    if settings.ragas_judge_provider == "local":
        from langchain_community.chat_models import ChatOllama
        from langchain_community.embeddings import HuggingFaceEmbeddings

        llm = ChatOllama(base_url=settings.ollama_host, model=settings.ragas_judge_ollama_model)
        embeddings = HuggingFaceEmbeddings(model_name=settings.local_embed_model)

    elif settings.ragas_judge_provider == "bedrock":
        from langchain_aws import BedrockEmbeddings, ChatBedrockConverse

        # ChatBedrockConverse (the unified Converse API) rather than the
        # older ChatBedrock (per-provider InvokeModel API) — the latter's
        # DeepSeek payload builder is broken (raises ValidationException:
        # missing field `messages`).
        llm = ChatBedrockConverse(
            model_id=settings.ragas_judge_bedrock_model, region_name=settings.aws_region
        )
        embeddings = BedrockEmbeddings(
            model_id=settings.bedrock_embed_model, region_name=settings.aws_region
        )

    else:
        raise ValueError(f"Unknown ragas_judge_provider: {settings.ragas_judge_provider!r}")

    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(embeddings)


def _run_ragas(records: list[dict], settings) -> dict:
    """Run RAGAS metrics on the collected records."""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    from ragas.run_config import RunConfig

    ds = Dataset.from_list(records)
    llm, embeddings = _build_ragas_judge(settings)

    # RAGAS defaults to max_workers=16 — far more concurrent judge calls than
    # either a CPU-bound local Ollama model or an on-demand Bedrock quota can
    # sustain (observed as widespread TimeoutErrors against Ollama, and
    # ThrottlingException against Bedrock even at max_workers=2 — this
    # account's on-demand TPS quota for this model is evidently very low).
    # Fully serial avoids both failure modes.
    run_config = RunConfig(max_workers=1)

    logger.info(
        "Running RAGAS evaluation on %d questions using '%s' judge provider …",
        len(records), settings.ragas_judge_provider,
    )
    score = evaluate(
        ds,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ],
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
    )

    # numeric_only=True: the DataFrame also carries the original question/
    # answer/contexts columns alongside the numeric metric scores, and
    # pandas 2.x's .mean() no longer silently skips non-numeric columns.
    return score.to_pandas().mean(numeric_only=True).to_dict()


# ── MLflow logging ─────────────────────────────────────────────────────────────

def _log_to_mlflow(metrics: dict, experiment: str, golden_path: str, out_path: str) -> None:
    """Log metrics and artifacts to MLflow."""
    import mlflow

    mlflow.set_tracking_uri("http://localhost:5001")
    mlflow.set_experiment(experiment)

    with mlflow.start_run():
        mlflow.log_metrics({
            k: float(v) for k, v in metrics.items()
            if isinstance(v, (int, float))
        })
        mlflow.log_artifact(golden_path, artifact_path="eval")
        mlflow.log_artifact(out_path,    artifact_path="eval")
        mlflow.log_param("faithfulness_threshold", FAITHFULNESS_THRESHOLD)
        mlflow.log_param("num_questions", metrics.get("num_questions", 0))

    logger.info("Metrics logged to MLflow at http://localhost:5001")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Vyom RAGAS evaluation harness")
    parser.add_argument("--golden",           default="eval/golden.jsonl",           help="Path to golden Q&A file")
    parser.add_argument("--golden-multiturn", default="eval/golden_multiturn.jsonl", help="Path to multi-turn conversation golden file (optional — skipped if missing)")
    parser.add_argument("--no-multiturn",     action="store_true",                   help="Skip multi-turn conversations even if the file exists")
    parser.add_argument("--out",        default="eval/results.json",  help="Path to write results JSON")
    parser.add_argument("--experiment", default="vyom-eval",          help="MLflow experiment name")
    parser.add_argument("--questions",  type=int, default=None,       help="Limit to first N single-turn questions (for quick testing)")
    args = parser.parse_args()

    # Load golden set
    golden_path = Path(args.golden)
    if not golden_path.exists():
        logger.error("Golden file not found: %s", golden_path)
        sys.exit(1)

    golden = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if args.questions:
        golden = golden[: args.questions]
        logger.info("Limited to first %d questions", args.questions)

    logger.info("Loaded %d questions from %s", len(golden), golden_path)

    # Load multi-turn conversations — optional, skipped if the file is
    # absent (unlike --golden, which is required). Kept entirely separate
    # from --questions' slicing since a conversation isn't a single item.
    golden_multiturn: list[dict] = []
    if not args.no_multiturn:
        mt_path = Path(args.golden_multiturn)
        if mt_path.exists():
            golden_multiturn = [
                json.loads(line)
                for line in mt_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            num_turns = sum(len(c["turns"]) for c in golden_multiturn)
            logger.info(
                "Loaded %d multi-turn conversations (%d turns total) from %s",
                len(golden_multiturn), num_turns, mt_path,
            )
        else:
            logger.info("No multi-turn golden file at %s — skipping", mt_path)

    # Load settings
    from vyom.config import get_settings
    settings = get_settings()

    # Run pipeline on all questions
    records = asyncio.run(_build_eval_dataset(golden, settings, golden_multiturn))

    # Add question count to metrics later
    num_questions = len(records)

    # Run RAGAS
    try:
        metrics = _run_ragas(records, settings)
    except Exception as exc:
        logger.error("RAGAS evaluation failed: %s", exc)
        logger.error(
            "Judge LLM uses VYOM_RAGAS_JUDGE_PROVIDER ('%s') — for 'local', check "
            "Ollama is running; for 'bedrock', check AWS credentials.",
            settings.ragas_judge_provider,
        )
        sys.exit(1)

    metrics["num_questions"] = num_questions

    # Print results
    print("\n" + "=" * 60)
    print("VYOM EVAL RESULTS")
    print("=" * 60)
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k:<30} {v:.4f}")
        else:
            print(f"  {k:<30} {v}")
    print("=" * 60 + "\n")

    # Write results JSON
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Results written to %s", out_path)

    # Log to MLflow
    try:
        _log_to_mlflow(metrics, args.experiment, str(golden_path), str(out_path))
    except Exception as exc:
        logger.warning("MLflow logging failed (is MLflow running?): %s", exc)

    # CI gate — fail if faithfulness is below threshold.
    # NaN (every faithfulness judge call errored/timed out) must fail loudly:
    # NaN comparisons are always False in Python, so `nan < threshold` silently
    # passes the gate unless checked explicitly.
    faithfulness_score = metrics.get("faithfulness", float("nan"))
    if math.isnan(faithfulness_score):
        print(
            "EVAL FAILED: faithfulness is NaN — every faithfulness judge call "
            "errored or timed out, so no score could be computed"
        )
        sys.exit(1)

    if faithfulness_score < FAITHFULNESS_THRESHOLD:
        print(
            f"EVAL FAILED: faithfulness {faithfulness_score:.4f} "
            f"< threshold {FAITHFULNESS_THRESHOLD}"
        )
        sys.exit(1)

    print(f"EVAL PASSED: faithfulness {faithfulness_score:.4f} >= {FAITHFULNESS_THRESHOLD}")


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg's async pool requires a selector-based loop; asyncio.run()
        # defaults to ProactorEventLoop on Windows, which it explicitly rejects.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()