"""Vyom — typed config loaded from .env (prefix: VYOM_).

All settings live here. Nothing else in the codebase reads os.environ directly.
Switch from local dev to AWS deploy by changing VYOM_PROVIDER=bedrock — nothing else changes.
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
    embedding_dim: int = 384

    # ── Local provider (free dev) ─────────────────────────────────────────────
    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    local_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # ── Bedrock provider (AWS deploy) ─────────────────────────────────────────
    aws_region: str = "ap-south-1"
    bedrock_embed_model: str = "amazon.titan-embed-text-v2:0"
    bedrock_gen_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_rerank_model: str = "amazon.rerank-v1:0"

    # ── Data sources ──────────────────────────────────────────────────────────
    bse_download_folder: str = "./data/bse"
    s3_bucket: str = "vyom-raw-data"

    # ── Retrieval ─────────────────────────────────────────────────────────────
    top_k: int = 20
    rerank_top_n: int = 5
    max_rewrite_loops: int = 2

    # ── API ───────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"
    rate_limit: str = "30/minute"

    # ── Enabled sources ───────────────────────────────────────────────────────
    enabled_sources: str = "bse,sebi,rbi,cross"

    @property
    def sources(self) -> list[str]:
        return [s.strip() for s in self.enabled_sources.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — .env is parsed exactly once per process."""
    return Settings()