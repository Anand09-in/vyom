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
        return SentenceTransformer(
            self._s.local_embed_model,
            trust_remote_code=True,
            truncate_dim=self._s.embedding_dim,
        )

    @cached_property
    def _reranker(self):
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker model %s …", self._s.local_rerank_model)
        return CrossEncoder(self._s.local_rerank_model)

    # ── Provider interface ────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed models are trained with asymmetric query/document
        # prefixes — this one is for indexed content, not queries. Embedding
        # without it (or with the wrong one) still "works" but silently
        # degrades retrieval quality, since the model wasn't trained that way.
        prefixed = [f"search_document: {t}" for t in texts]
        vectors = self._embedder.encode(
            prefixed,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        self._empty_cuda_cache()
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embedder.encode(
            [f"search_query: {text}"],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        self._empty_cuda_cache()
        return vectors[0].tolist()

    @staticmethod
    def _empty_cuda_cache() -> None:
        # On GPU, torch caches freed tensor memory for reuse rather than
        # returning it to the driver — fine for a single batch, but across
        # hundreds of embed() calls in a long-running ingest, the cache
        # grows until VRAM is exhausted and every allocation has to fight
        # for fragmented memory (observed: ~1s/batch degrading to 400s+/batch
        # once a 6GB card filled up). Releasing after every call keeps
        # steady-state usage flat instead of monotonically growing.
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

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
        self._empty_cuda_cache()
        ranked = sorted(
            (RerankResult(index=i, score=float(s)) for i, s in enumerate(scores)),
            key=lambda r: r.score,
            reverse=True,
        )
        return ranked[:top_n] if top_n else ranked