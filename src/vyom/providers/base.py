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


class GuardrailBlocked(Exception):
    """Raised by generate() when a guardrail intervenes on the full
    constructed prompt (context + history + question) — distinct from
    check_guardrail(), which screens the raw query before retrieval ever
    runs. Callers that already retrieved real chunks before hitting this
    (i.e. anyone catching it around the final answer-generation call)
    should discard those citations along with the answer — they were
    never actually used in the text this exception carries."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Provider(ABC):
    """Abstract backend for the three model operations RAG needs."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input, order preserved."""

    def embed_query(self, text: str) -> list[float]:
        """Convenience wrapper — embed a single query string."""
        return self.embed([text])[0]

    @abstractmethod
    def generate(
        self, prompt: str, *, system: str | None = None, apply_guardrail: bool = True
    ) -> str:
        """Generate a complete answer for a prompt.

        apply_guardrail=False is for internal-only calls whose output is
        never shown to the user directly (query condensing, HyDE) — their
        inputs were already screened when originally submitted (the raw
        query via check_guardrail(), history via a prior guardrail-checked
        generate() call), so re-screening the same content on every
        follow-up turn is redundant and, empirically, prone to false
        positives on ordinary multi-turn conversations (the "conversation
        transcript + rewrite instruction" shape itself reads as
        injection-like to the classifier). The final user-facing generate()
        call — the one building the actual answer — always keeps this True.
        """

    @abstractmethod
    def stream(
        self, prompt: str, *, system: str | None = None, apply_guardrail: bool = True
    ) -> Iterator[str]:
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

    def check_guardrail(self, text: str) -> str | None:
        """Fast up-front check on raw user input, before any retrieval work
        runs. Returns a block message if the input should be rejected
        outright, or None if it's fine to proceed.

        Deliberately separate from the guardrailConfig already applied
        inside generate()/stream() — that one screens the *full* constructed
        prompt (retrieved context + history + question) right before the
        final LLM call, which is necessary but happens only after retrieval
        has already spent its embedding/search/rerank work. This one runs
        first, on the raw query alone, so an obvious injection attempt gets
        rejected without paying for retrieval at all. Default: no-op (never
        blocks) — only BedrockProvider actually implements a check, since
        Guardrails is a Bedrock-specific feature.
        """
        return None