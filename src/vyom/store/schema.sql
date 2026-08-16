-- Vyom database schema
-- Applied automatically by Docker on first start via docker-entrypoint-initdb.d
-- Every chunk table gets both HNSW (dense cosine) and GIN (BM25 full-text) indexes
-- so hybrid search works without any extra setup.

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Source 1: BSE / NSE corporate filings ────────────────────────────────────

CREATE TABLE IF NOT EXISTS filings (
    id           BIGSERIAL    PRIMARY KEY,
    company_name TEXT         NOT NULL,
    bse_code     TEXT,
    nse_symbol   TEXT,
    filing_type  TEXT         NOT NULL,  -- 'annual_report' | 'quarterly_result' | 'announcement'
    filing_date  DATE         NOT NULL,
    source_url   TEXT         NOT NULL,
    pdf_s3_key   TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (bse_code, filing_type, filing_date)
);

CREATE TABLE IF NOT EXISTS filing_chunks (
    id           BIGSERIAL    PRIMARY KEY,
    filing_id    BIGINT       NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    section      TEXT,                   -- 'mda' | 'risk_factors' | 'financials' | 'notes'
    chunk_index  INT          NOT NULL,
    content      TEXT         NOT NULL,
    context_prefix TEXT,                 -- contextual-retrieval prefix sentence
    embedding    vector(512),
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('english', coalesce(context_prefix, '') || ' ' || content)
                 ) STORED,
    UNIQUE (filing_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS filing_chunks_hnsw
    ON filing_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS filing_chunks_gin
    ON filing_chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS filing_chunks_filing_id
    ON filing_chunks (filing_id);

-- ── Source 2: SEBI circulars and regulatory orders ────────────────────────────

CREATE TABLE IF NOT EXISTS circulars (
    id              BIGSERIAL    PRIMARY KEY,
    circular_number TEXT         NOT NULL UNIQUE,
    issuing_body    TEXT         NOT NULL DEFAULT 'SEBI',
    title           TEXT         NOT NULL,
    category        TEXT,               -- 'NBFC' | 'BRSR' | 'enforcement' | 'market_conduct'
    issue_date      DATE,
    source_url      TEXT,
    pdf_s3_key      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS circular_chunks (
    id              BIGSERIAL    PRIMARY KEY,
    circular_id     BIGINT       NOT NULL REFERENCES circulars(id) ON DELETE CASCADE,
    chunk_index     INT          NOT NULL,
    content         TEXT         NOT NULL,
    embedding       vector(512),
    tsv             tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', content)
                    ) STORED,
    UNIQUE (circular_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS circular_chunks_hnsw
    ON circular_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS circular_chunks_gin
    ON circular_chunks USING gin (tsv);

-- ── Source 3: RBI DBIE macro economic data ────────────────────────────────────

CREATE TABLE IF NOT EXISTS rbi_series (
    id          BIGSERIAL    PRIMARY KEY,
    series_id   TEXT         NOT NULL UNIQUE,  -- e.g. 'REPO_RATE', 'CPI_COMBINED'
    title       TEXT         NOT NULL,
    category    TEXT,                          -- 'monetary_policy' | 'inflation' | 'credit' | 'forex'
    frequency   TEXT,                          -- 'monthly' | 'quarterly' | 'weekly'
    units       TEXT,
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rbi_observations (
    id          BIGSERIAL    PRIMARY KEY,
    series_id   TEXT         NOT NULL REFERENCES rbi_series(series_id) ON DELETE CASCADE,
    obs_date    DATE         NOT NULL,
    value       FLOAT,
    UNIQUE (series_id, obs_date)
);

-- Narrative text summaries of the time-series — these are what get embedded.
-- Raw numbers (6.50) don't embed usefully. Narrative text does.
CREATE TABLE IF NOT EXISTS rbi_chunks (
    id          BIGSERIAL    PRIMARY KEY,
    series_id   TEXT         NOT NULL REFERENCES rbi_series(series_id) ON DELETE CASCADE,
    period      TEXT         NOT NULL,          -- e.g. '2024-Q3', '2024-10'
    content     TEXT         NOT NULL,          -- human-readable narrative summary
    embedding   vector(512),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (series_id, period)
);

CREATE INDEX IF NOT EXISTS rbi_chunks_hnsw
    ON rbi_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS rbi_chunks_gin
    ON rbi_chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS rbi_obs_date
    ON rbi_observations (series_id, obs_date);

-- ── Observability ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS query_log (
    id               BIGSERIAL    PRIMARY KEY,
    user_id          TEXT,                       -- Cognito `sub` — see api/auth.py
    session_id       TEXT,
    query            TEXT         NOT NULL,
    rewritten_query  TEXT,
    sources_used     TEXT[],                    -- ['bse', 'rbi'] etc.
    chunks_retrieved INT,
    faithfulness     FLOAT,
    latency_ms       INT,
    tokens_used      INT,
    provider         TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id              BIGSERIAL    PRIMARY KEY,
    query_log_id    BIGINT       NOT NULL REFERENCES query_log(id) ON DELETE CASCADE,
    rating          SMALLINT     NOT NULL CHECK (rating IN (-1, 1)),  -- -1 = bad, 1 = good
    comment         TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);