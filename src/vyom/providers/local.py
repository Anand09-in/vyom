"""Local provider — BGE-M3 embeddings + BGE reranker + Ollama generation.

Costs $0. All models run on your machine.
Heavy ML imports (torch, sentence-transformers) are deferred to first use
so the package imports fast and the cloud Lambda path never needs torch.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import cached_property

import httpx

from vyom.config import Settings
from vyom.providers.base import Provider, RerankResult

logger = logging.getLogger(__name__)


class LocalProvider(Provider):
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    # ── lazy-loaded models ────────────────────────────────────────────────────

    @cached_property
    def _embedder(self):
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %s …", self._s.local_embed_model)
        return SentenceTransformer(self._s.local_embed_model)

    @cached_property
    def _reranker(self):
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker model %s …", self._s.local_rerank_model)
        return CrossEncoder(self._s.local_rerank_model)

    # ── Provider interface ────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embedder.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        resp = httpx.post(
            f"{self._s.ollama_host}/api/generate",
            json={
                "model": self._s.ollama_model,
                "prompt": prompt,
                "system": system or "",
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    def stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{self._s.ollama_host}/api/generate",
            json={
                "model": self._s.ollama_model,
                "prompt": prompt,
                "system": system or "",
                "stream": True,
            },
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if token := chunk.get("response"):
                        yield token

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        scores = self._reranker.predict([(query, doc) for doc in documents])
        ranked = sorted(
            (RerankResult(index=i, score=float(s)) for i, s in enumerate(scores)),
            key=lambda r: r.score,
            reverse=True,
        )
        return ranked[:top_n] if top_n else ranked