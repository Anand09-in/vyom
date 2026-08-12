"""Abstract Provider — the single seam between app logic and vendor SDKs.

Every model operation in Vyom goes through this interface.
Swap VYOM_PROVIDER=local → bedrock and the whole system switches
without touching retrieval, serving, or eval code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class RerankResult:
    """One reranked document, pointing back at its position in the input list."""
    index: int
    score: float


class Provider(ABC):
    """Abstract backend for the three model operations RAG needs."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input, order preserved."""

    def embed_query(self, text: str) -> list[float]:
        """Convenience wrapper — embed a single query string."""
        return self.embed([text])[0]

    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate a complete answer for a prompt."""

    @abstractmethod
    def stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        """Yield generated tokens incrementally (used for SSE responses)."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Score documents against the query. Returns them sorted best-first."""