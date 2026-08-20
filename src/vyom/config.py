"""Vyom — typed config loaded from .env (prefix: VYOM_).

All settings live here. Nothing else in the codebase reads os.environ directly.

VYOM_PROVIDER=bedrock does NOT mean "everything via AWS" — it means
generation via Bedrock (the only role needing a model too large to run
locally). Embedding and reranking always run locally regardless of
VYOM_PROVIDER, since they're cheap and fast on local CPU/GPU with no
per-call API cost — see providers/bedrock.py for the reasoning.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VYOM_",
        extra="ignore",
    )

    # ── Provider ──────────────────────────────────────────────────────────────
    provider: Literal["local", "bedrock"] = "local"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql://vyom:vyom@localhost:5432/vyom"
    db_pool_min: int = 2
    db_pool_max: int = 10
    embedding_dim: int = 512

    # ── Conversation history (Redis) ─────────────────────────────────────────
    # Storage is unbounded — every turn is kept until a client explicitly
    # deletes it (no TTL, per design choice: better an explicit "New
    # conversation" action than a silent, surprising expiry). Only the last
    # history_recent_turns are ever sliced off and sent to the LLM (for query
    # condensation and the final generation prompt) — see store/history.py.
    redis_url: str = "redis://localhost:6379/0"
    history_recent_turns: int = 5

    # ── Local provider (free dev) ─────────────────────────────────────────────
    # nomic-embed-text-v1.5: English, 8192-token context (our chunker's
    # 512-word chunks exceeded MiniLM's 256-token limit and were being
    # silently truncated), higher MTEB retrieval score, truncated to
    # embedding_dim via native Matryoshka support — no schema change needed.
    local_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    local_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    # ── Bedrock provider (AWS deploy) ─────────────────────────────────────────
    aws_region: str = "ap-south-1"
    # Used only by the RAGAS judge's answer_relevancy metric (eval/run_ragas.py),
    # not by BedrockProvider — embedding always runs locally, see module docstring.
    bedrock_embed_model: str = "amazon.titan-embed-text-v2:0"
    # Mistral Large 3, not Claude — Anthropic models on this account require
    # an AWS Marketplace subscription with a valid payment instrument, which
    # isn't set up yet. Deliberately a different model family from
    # ragas_judge_bedrock_model (DeepSeek) below, so the judge isn't scoring
    # output from its own model family. Works on-demand, no inference profile
    # needed, 100 RPM / 100M TPM quota (Llama 3 70B's ~4 RPM throttled heavily).
    bedrock_gen_model: str = "mistral.mistral-large-3-675b-instruct"
    # Prompt-injection / off-topic defense on generation calls only — see
    # infra/main.tf's aws_bedrock_guardrail.vyom. Applied via the Converse
    # API's guardrailConfig, not a code-level filter, so it's enforced
    # server-side by Bedrock regardless of what BedrockProvider does.
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = "1"

    # ── Auth (Cognito) ─────────────────────────────────────────────────────────
    # Every route except /health requires a valid Cognito-issued JWT — see
    # api/deps.py's get_current_user. Values come from infra/main.tf's
    # outputs after `terraform apply` (cognito_user_pool_id, etc.).
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_issuer_url: str = ""

    # ── Data sources ──────────────────────────────────────────────────────────
    bse_download_folder: str = "./data/bse"
    s3_bucket: str = "vyom-raw-data"
    # Live web search (current prices, same-day news) — see
    # retrieve/live_search.py. "live" stays in enabled_sources by default
    # regardless of whether this is set; retrieve_all silently contributes
    # nothing if it's empty, so the feature degrades gracefully rather than
    # needing separate "enabled" vs "configured" bookkeeping.
    tavily_api_key: str = ""

    # ── Eval (RAGAS judge) ────────────────────────────────────────────────────
    # Independent of `provider`/`bedrock_gen_model`: the judge deliberately
    # uses a third model family (DeepSeek), different from both the local
    # Ollama model and bedrock_gen_model (Mistral), so it isn't scoring
    # output from its own model family.
    ragas_judge_provider: Literal["local", "bedrock"] = "local"
    # Only used when ragas_judge_provider == "local".
    ragas_judge_ollama_model: str = "qwen2.5:7b"
    # Only used when ragas_judge_provider == "bedrock". DeepSeek V3.2 works
    # on-demand with no inference profile or Marketplace subscription
    # needed, and its on-demand quota (100 RPM / 100M TPM) is far higher
    # than Llama 3 70B's, which throttled
    # heavily even at serial (max_workers=1) execution.
    ragas_judge_bedrock_model: str = "deepseek.v3.2"

    # ── Retrieval ─────────────────────────────────────────────────────────────
    top_k: int = 20
    rerank_top_n: int = 5
    max_rewrite_loops: int = 2

    # ── API ───────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"
    rate_limit: str = "30/minute"
    # Structured (pure-JSON, one line per request) events for CloudWatch
    # metric filters — deliberately a SEPARATE file from the human-readable
    # app log (journald/stdout), since a metric filter needs to parse each
    # line as JSON and the normal logging format's timestamp/level/name
    # prefix would break that. Relative by default so it works unchanged on
    # both Windows dev (relative to the repo root) and the EC2 deploy
    # (relative to systemd's WorkingDirectory=/opt/vyom) — see
    # infra/main.tf's CloudWatch Agent config, which tails this same path.
    event_log_path: str = "logs/events.jsonl"

    # ── Enabled sources ───────────────────────────────────────────────────────
    enabled_sources: str = "bse,sebi,rbi,cross,live"

    @property
    def sources(self) -> list[str]:
        return [s.strip() for s in self.enabled_sources.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — .env is parsed exactly once per process."""
    return Settings()