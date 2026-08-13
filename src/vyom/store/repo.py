"""Vyom repository — every SQL statement lives here, nowhere else.

Three hybrid search methods (one per source), each using the same pattern:
  1. Dense ANN via pgvector HNSW (cosine similarity)
  2. Sparse BM25 via Postgres tsvector
  3. Reciprocal Rank Fusion (RRF) to merge the two lists in one SQL round-trip

This avoids a separate vector database and keeps infra minimal (one RDS instance).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from vyom.config import Settings

logger = logging.getLogger(__name__)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FilingChunk:
    id: int
    filing_id: int
    company_name: str
    section: str | None
    content: str
    source: str = "bse"
    rrf_score: float = 0.0


@dataclass
class CircularChunk:
    id: int
    circular_id: int
    circular_number: str
    title: str
    category: str | None
    content: str
    source: str = "sebi"
    rrf_score: float = 0.0


@dataclass
class RbiChunk:
    id: int
    series_id: str
    period: str
    content: str
    source: str = "rbi"
    rrf_score: float = 0.0


# ── Repository ────────────────────────────────────────────────────────────────

class Repository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    # ── BSE filing writes ─────────────────────────────────────────────────────

    async def upsert_filing(
        self,
        company_name: str,
        bse_code: str | None,
        nse_symbol: str | None,
        filing_type: str,
        filing_date: str,
        source_url: str,
        pdf_s3_key: str | None = None,
    ) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO filings
                    (company_name, bse_code, nse_symbol, filing_type, filing_date, source_url, pdf_s3_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (bse_code, filing_type, filing_date)
                DO UPDATE SET source_url = EXCLUDED.source_url
                RETURNING id
                """,
                (company_name, bse_code, nse_symbol, filing_type,
                 filing_date, source_url, pdf_s3_key),
            )
            row = await cur.fetchone()
            return row["id"]

    async def insert_filing_chunks(self, filing_id: int, chunks: list[dict]) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO filing_chunks
                        (filing_id, section, chunk_index, content, context_prefix, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (filing_id, chunk_index) DO NOTHING
                    """,
                    [
                        (
                            filing_id,
                            c["section"],
                            c["index"],
                            c["content"],
                            c.get("context_prefix"),
                            c["embedding"],
                        )
                        for c in chunks
                    ],
                )

    # ── BSE hybrid search ─────────────────────────────────────────────────────

    async def hybrid_search_bse(
        self,
        embedding: list[float],
        query: str,
        top_k: int = 20,
        company: str | None = None,
    ) -> list[FilingChunk]:
        company_filter = "AND f.company_name ILIKE %(company)s" if company else ""
        sql = f"""
        WITH dense AS (
            SELECT fc.id,
                   ROW_NUMBER() OVER (ORDER BY fc.embedding <=> %(vec)s::vector) AS rank
            FROM filing_chunks fc
            JOIN filings f ON f.id = fc.filing_id
            WHERE fc.embedding IS NOT NULL {company_filter}
            LIMIT %(k)s
        ),
        sparse AS (
            SELECT fc.id,
                   ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fc.tsv, q) DESC) AS rank
            FROM filing_chunks fc
            JOIN filings f ON f.id = fc.filing_id,
                 plainto_tsquery('english', %(q)s) q
            WHERE fc.tsv @@ q {company_filter}
            LIMIT %(k)s
        ),
        rrf AS (
            SELECT id, SUM(1.0 / (60 + rank)) AS score
            FROM (SELECT * FROM dense UNION ALL SELECT * FROM sparse) combined
            GROUP BY id
        )
        SELECT
            fc.id, fc.filing_id, f.company_name, fc.section, fc.content,
            'bse' AS source, r.score AS rrf_score
        FROM rrf r
        JOIN filing_chunks fc ON fc.id = r.id
        JOIN filings f ON f.id = fc.filing_id
        ORDER BY r.score DESC
        LIMIT %(k)s
        """
        params = {"vec": embedding, "q": query, "k": top_k, "company": f"%{company}%"}
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
        return [FilingChunk(**{k: r[k] for k in FilingChunk.__dataclass_fields__}) for r in rows]

    # ── SEBI circular writes ──────────────────────────────────────────────────

    async def upsert_circular(
        self,
        circular_number: str,
        title: str,
        category: str | None = None,
        issue_date: str | None = None,
        source_url: str | None = None,
        pdf_s3_key: str | None = None,
    ) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO circulars
                    (circular_number, title, category, issue_date, source_url, pdf_s3_key)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (circular_number)
                DO UPDATE SET title = EXCLUDED.title
                RETURNING id
                """,
                (circular_number, title, category, issue_date, source_url, pdf_s3_key),
            )
            row = await cur.fetchone()
            return row["id"]

    async def insert_circular_chunks(self, circular_id: int, chunks: list[dict]) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO circular_chunks (circular_id, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (circular_id, chunk_index) DO NOTHING
                    """,
                    [(circular_id, c["index"], c["content"], c["embedding"]) for c in chunks],
                )

    # ── SEBI hybrid search ────────────────────────────────────────────────────

    async def hybrid_search_sebi(
        self,
        embedding: list[float],
        query: str,
        top_k: int = 20,
    ) -> list[CircularChunk]:
        sql = """
        WITH dense AS (
            SELECT cc.id,
                   ROW_NUMBER() OVER (ORDER BY cc.embedding <=> %(vec)s::vector) AS rank
            FROM circular_chunks cc
            WHERE cc.embedding IS NOT NULL
            LIMIT %(k)s
        ),
        sparse AS (
            SELECT cc.id,
                   ROW_NUMBER() OVER (ORDER BY ts_rank_cd(cc.tsv, q) DESC) AS rank
            FROM circular_chunks cc,
                 plainto_tsquery('english', %(q)s) q
            WHERE cc.tsv @@ q
            LIMIT %(k)s
        ),
        rrf AS (
            SELECT id, SUM(1.0 / (60 + rank)) AS score
            FROM (SELECT * FROM dense UNION ALL SELECT * FROM sparse) combined
            GROUP BY id
        )
        SELECT
            cc.id, cc.circular_id, c.circular_number, c.title, c.category,
            cc.content, 'sebi' AS source, r.score AS rrf_score
        FROM rrf r
        JOIN circular_chunks cc ON cc.id = r.id
        JOIN circulars c ON c.id = cc.circular_id
        ORDER BY r.score DESC
        LIMIT %(k)s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, {"vec": embedding, "q": query, "k": top_k})
                rows = await cur.fetchall()
        return [
            CircularChunk(**{k: r[k] for k in CircularChunk.__dataclass_fields__})
            for r in rows
        ]

    # ── RBI series writes ─────────────────────────────────────────────────────

    async def upsert_rbi_series(
        self,
        series_id: str,
        title: str,
        category: str | None = None,
        frequency: str | None = None,
        units: str | None = None,
        notes: str | None = None,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO rbi_series (series_id, title, category, frequency, units, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id) DO UPDATE SET title = EXCLUDED.title
                """,
                (series_id, title, category, frequency, units, notes),
            )

    async def upsert_rbi_observations(
        self, series_id: str, observations: list[dict]
    ) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO rbi_observations (series_id, obs_date, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (series_id, obs_date) DO UPDATE SET value = EXCLUDED.value
                    """,
                    [(series_id, o["date"], o["value"]) for o in observations],
                )

    async def insert_rbi_chunks(self, chunks: list[dict]) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO rbi_chunks (series_id, period, content, embedding)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (series_id, period)
                    DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding
                    """,
                    [
                        (c["series_id"], c["period"], c["content"], c["embedding"])
                        for c in chunks
                    ],
                )

    # ── RBI hybrid search ─────────────────────────────────────────────────────

    async def hybrid_search_rbi(
        self,
        embedding: list[float],
        query: str,
        top_k: int = 10,
    ) -> list[RbiChunk]:
        sql = """
        WITH dense AS (
            SELECT rc.id,
                   ROW_NUMBER() OVER (ORDER BY rc.embedding <=> %(vec)s::vector) AS rank
            FROM rbi_chunks rc
            WHERE rc.embedding IS NOT NULL
            LIMIT %(k)s
        ),
        sparse AS (
            SELECT rc.id,
                   ROW_NUMBER() OVER (ORDER BY ts_rank_cd(rc.tsv, q) DESC) AS rank
            FROM rbi_chunks rc,
                 plainto_tsquery('english', %(q)s) q
            WHERE rc.tsv @@ q
            LIMIT %(k)s
        ),
        rrf AS (
            SELECT id, SUM(1.0 / (60 + rank)) AS score
            FROM (SELECT * FROM dense UNION ALL SELECT * FROM sparse) combined
            GROUP BY id
        )
        SELECT
            rc.id, rc.series_id, rc.period, rc.content,
            'rbi' AS source, r.score AS rrf_score
        FROM rrf r
        JOIN rbi_chunks rc ON rc.id = r.id
        ORDER BY r.score DESC
        LIMIT %(k)s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, {"vec": embedding, "q": query, "k": top_k})
                rows = await cur.fetchall()
        return [RbiChunk(**{k: r[k] for k in RbiChunk.__dataclass_fields__}) for r in rows]

    # ── Observability ─────────────────────────────────────────────────────────

    async def log_query(self, **kwargs: Any) -> int:
        cols = ", ".join(kwargs)
        placeholders = ", ".join(f"%({k})s" for k in kwargs)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"INSERT INTO query_log ({cols}) VALUES ({placeholders}) RETURNING id",
                kwargs,
            )
            row = await cur.fetchone()
            return row["id"]

    async def log_feedback(
        self, query_log_id: int, rating: int, comment: str | None = None
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO feedback (query_log_id, rating, comment) VALUES (%s, %s, %s)",
                (query_log_id, rating, comment),
            )


# ── Pool factory ──────────────────────────────────────────────────────────────

async def create_pool(settings: Settings) -> AsyncConnectionPool:
    """Create and return an async connection pool. Call pool.open() before use."""
    return AsyncConnectionPool(
        settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        kwargs={"row_factory": dict_row},
        open=False,
    )