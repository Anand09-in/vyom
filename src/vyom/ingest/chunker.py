"""Text chunking utilities used by all three ingest pipelines.

Two functions:
  chunk_text()        — splits raw text into overlapping word-window chunks
  add_context_prefix() — prepends a document-level summary to each chunk
                         (contextual retrieval — improves embedding quality)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    section: str
    index: int
    content: str
    context_prefix: str = field(default="")


def chunk_text(
    text: str,
    section: str = "general",
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """
    Split text into overlapping chunks by word count.

    Args:
        text:       Raw text to split.
        section:    Label for this section (e.g. 'mda', 'risk_factors').
        chunk_size: Target words per chunk.
        overlap:    Words shared between consecutive chunks.

    Returns:
        List of Chunk objects, each with a unique index.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[Chunk] = []
    i = 0
    idx = 0

    while i < len(words):
        window = words[i : i + chunk_size]
        chunks.append(Chunk(section=section, index=idx, content=" ".join(window)))
        i += chunk_size - overlap
        idx += 1

    return chunks


def add_context_prefix(chunks: list[Chunk], document_summary: str) -> list[Chunk]:
    """
    Prepend a short document-level context sentence to each chunk.

    This is the "contextual retrieval" technique — it dramatically improves
    retrieval precision because each chunk becomes self-contained even when
    retrieved in isolation.

    Example prefix:
        "From HDFC Bank's FY2025 annual report: <chunk content>"
    """
    prefix = document_summary.strip()[:300]
    for chunk in chunks:
        chunk.context_prefix = f"From {prefix}:"
    return chunks