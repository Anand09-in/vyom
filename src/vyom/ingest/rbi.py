"""RBI macro data ingest — pulls key economic series and stores them as
narrative text chunks that can be embedded and retrieved semantically.

Design decision: raw numbers (6.50) don't embed usefully.
We convert them to narrative text:
  "Repo rate held at 6.5% for Q3-2024, third consecutive unchanged MPC meeting.
   Trend: stable. Latest value: 6.50 as of 2024-10-04."
This retrieves correctly when someone asks "what is the repo rate trend".

Sources: RBI publishes these as public CSV/JSON — no API key needed.
We use the RBI DBIE indirect download URLs and the RBI website directly.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime

import httpx

from vyom.config import Settings, get_settings
from vyom.ingest.chunker import chunk_text, add_context_prefix

logger = logging.getLogger(__name__)

# ── RBI series we track ────────────────────────────────────────────────────────
# Each entry: series_id, title, category, frequency, units, fetch_url
# Using RBI's publicly accessible data endpoints

RBI_SERIES = [
    {
        "series_id": "REPO_RATE",
        "title": "RBI Repo Rate",
        "category": "monetary_policy",
        "frequency": "event-based",
        "units": "percent per annum",
        "description": "The rate at which RBI lends money to commercial banks. "
                       "Primary monetary policy tool to control inflation and liquidity.",
    },
    {
        "series_id": "CPI_COMBINED",
        "title": "Consumer Price Index — Combined",
        "category": "inflation",
        "frequency": "monthly",
        "units": "index",
        "description": "Measures retail inflation across food, fuel, and core categories. "
                       "RBI targets CPI inflation at 4% with a 2% tolerance band.",
    },
    {
        "series_id": "BANK_CREDIT_GROWTH",
        "title": "Bank Credit Growth (YoY)",
        "category": "credit",
        "frequency": "fortnightly",
        "units": "percent",
        "description": "Year-on-year growth in total bank credit. "
                       "Indicator of economic activity and lending conditions.",
    },
    {
        "series_id": "FOREX_RESERVES",
        "title": "Foreign Exchange Reserves",
        "category": "forex",
        "frequency": "weekly",
        "units": "USD billion",
        "description": "India's total foreign exchange reserves including gold. "
                       "Indicator of external sector strength and INR stability.",
    },
    {
        "series_id": "INR_USD",
        "title": "INR/USD Exchange Rate",
        "category": "forex",
        "frequency": "daily",
        "units": "INR per USD",
        "description": "Indian Rupee to US Dollar exchange rate. "
                       "Affects import costs, inflation, and corporate earnings.",
    },
    {
        "series_id": "IIP_GENERAL",
        "title": "Index of Industrial Production — General",
        "category": "production",
        "frequency": "monthly",
        "units": "index",
        "description": "Measures industrial output across mining, manufacturing, electricity. "
                       "Key indicator of economic momentum.",
    },
    {
        "series_id": "FISCAL_DEFICIT",
        "title": "Central Government Fiscal Deficit",
        "category": "fiscal",
        "frequency": "monthly",
        "units": "INR crore",
        "description": "Difference between government revenue and expenditure. "
                       "Affects bond yields, inflation, and crowding out of private investment.",
    },
]

# Hardcoded recent RBI data (2023-2025)
# In production this would be fetched live from RBI DBIE
# Using hardcoded data for Phase 1 reliability — no scraping fragility
HARDCODED_DATA: dict[str, list[dict]] = {
    "REPO_RATE": [
        {"date": "2023-02-08", "value": 6.50},
        {"date": "2023-04-06", "value": 6.50},
        {"date": "2023-06-08", "value": 6.50},
        {"date": "2023-08-10", "value": 6.50},
        {"date": "2023-10-06", "value": 6.50},
        {"date": "2023-12-08", "value": 6.50},
        {"date": "2024-02-08", "value": 6.50},
        {"date": "2024-04-05", "value": 6.50},
        {"date": "2024-06-07", "value": 6.50},
        {"date": "2024-08-08", "value": 6.50},
        {"date": "2024-10-09", "value": 6.50},
        {"date": "2024-12-06", "value": 6.50},
        {"date": "2025-02-07", "value": 6.25},
        {"date": "2025-04-09", "value": 6.00},
    ],
    "CPI_COMBINED": [
        {"date": "2023-04-01", "value": 4.70},
        {"date": "2023-05-01", "value": 4.25},
        {"date": "2023-06-01", "value": 4.81},
        {"date": "2023-07-01", "value": 7.44},
        {"date": "2023-08-01", "value": 6.83},
        {"date": "2023-09-01", "value": 5.02},
        {"date": "2023-10-01", "value": 4.87},
        {"date": "2023-11-01", "value": 5.55},
        {"date": "2023-12-01", "value": 5.69},
        {"date": "2024-01-01", "value": 5.10},
        {"date": "2024-02-01", "value": 5.09},
        {"date": "2024-03-01", "value": 4.85},
        {"date": "2024-04-01", "value": 4.83},
        {"date": "2024-05-01", "value": 4.75},
        {"date": "2024-06-01", "value": 5.08},
        {"date": "2024-07-01", "value": 3.54},
        {"date": "2024-08-01", "value": 3.65},
        {"date": "2024-09-01", "value": 5.49},
        {"date": "2024-10-01", "value": 6.21},
        {"date": "2024-11-01", "value": 5.48},
        {"date": "2024-12-01", "value": 5.22},
        {"date": "2025-01-01", "value": 4.26},
        {"date": "2025-02-01", "value": 3.61},
    ],
    "BANK_CREDIT_GROWTH": [
        {"date": "2023-04-01", "value": 15.0},
        {"date": "2023-07-01", "value": 14.5},
        {"date": "2023-10-01", "value": 15.3},
        {"date": "2024-01-01", "value": 16.5},
        {"date": "2024-04-01", "value": 14.0},
        {"date": "2024-07-01", "value": 13.7},
        {"date": "2024-10-01", "value": 11.5},
        {"date": "2025-01-01", "value": 12.0},
    ],
    "FOREX_RESERVES": [
        {"date": "2023-04-01", "value": 578.8},
        {"date": "2023-07-01", "value": 603.0},
        {"date": "2023-10-01", "value": 583.5},
        {"date": "2024-01-01", "value": 617.2},
        {"date": "2024-04-01", "value": 643.2},
        {"date": "2024-07-01", "value": 668.0},
        {"date": "2024-10-01", "value": 701.2},
        {"date": "2025-01-01", "value": 623.0},
        {"date": "2025-03-01", "value": 658.8},
    ],
    "INR_USD": [
        {"date": "2023-04-01", "value": 81.9},
        {"date": "2023-07-01", "value": 82.1},
        {"date": "2023-10-01", "value": 83.3},
        {"date": "2024-01-01", "value": 83.1},
        {"date": "2024-04-01", "value": 83.5},
        {"date": "2024-07-01", "value": 83.7},
        {"date": "2024-10-01", "value": 84.0},
        {"date": "2025-01-01", "value": 86.5},
        {"date": "2025-03-01", "value": 85.8},
    ],
    "IIP_GENERAL": [
        {"date": "2023-04-01", "value": 4.5},
        {"date": "2023-07-01", "value": 5.8},
        {"date": "2023-10-01", "value": 11.7},
        {"date": "2024-01-01", "value": 3.8},
        {"date": "2024-04-01", "value": 5.0},
        {"date": "2024-07-01", "value": 4.8},
        {"date": "2024-10-01", "value": 3.5},
        {"date": "2025-01-01", "value": 5.0},
    ],
    "FISCAL_DEFICIT": [
        {"date": "2023-04-01", "value": 5.9},
        {"date": "2023-07-01", "value": 5.9},
        {"date": "2023-10-01", "value": 5.9},
        {"date": "2024-01-01", "value": 5.8},
        {"date": "2024-04-01", "value": 5.6},
        {"date": "2024-07-01", "value": 5.6},
        {"date": "2024-10-01", "value": 5.6},
        {"date": "2025-01-01", "value": 5.1},
    ],
}


def _build_narrative(
    series_id: str,
    title: str,
    description: str,
    category: str,
    units: str,
    observations: list[dict],
) -> list[dict]:
    """
    Convert raw observations into embeddable narrative text chunks.

    Groups observations by quarter and writes a human-readable summary
    for each period. Also writes one overall summary chunk.
    """
    if not observations:
        return []

    chunks: list[dict] = []
    values = [o["value"] for o in observations]
    dates  = [o["date"]  for o in observations]

    # Overall summary chunk
    trend = "rising" if values[-1] > values[0] else "falling" if values[-1] < values[0] else "stable"
    pct   = ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0

    summary = (
        f"RBI Data Summary — {title}\n"
        f"Category: {category.upper()} | Units: {units}\n"
        f"What it measures: {description}\n"
        f"Period: {dates[0]} to {dates[-1]}\n"
        f"Range: {min(values):.2f} – {max(values):.2f} {units}\n"
        f"Overall trend: {trend} ({pct:+.1f}% over the full period)\n"
        f"Latest value: {values[-1]:.2f} {units} as of {dates[-1]}\n"
        f"Series ID: {series_id}"
    )
    chunks.append({"series_id": series_id, "period": "summary", "content": summary})

    # Per-observation narrative chunks (group into quarters)
    def to_quarter(date_str: str) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"

    # Group by quarter
    quarters: dict[str, list[dict]] = {}
    for obs in observations:
        q = to_quarter(obs["date"])
        quarters.setdefault(q, []).append(obs)

    for period, period_obs in quarters.items():
        vals = [o["value"] for o in period_obs]
        avg  = sum(vals) / len(vals)
        t    = "rising" if vals[-1] > vals[0] else "falling" if vals[-1] < vals[0] else "stable"

        text = (
            f"RBI {title} — {period}\n"
            f"Category: {category.upper()}\n"
            f"Average: {avg:.2f} {units}\n"
            f"Trend this quarter: {t}\n"
            f"Latest in period: {vals[-1]:.2f} {units} as of {period_obs[-1]['date']}\n"
            f"Context: {description}"
        )
        chunks.append({"series_id": series_id, "period": period, "content": text})

    return chunks


async def run_rbi_ingest(settings: Settings | None = None) -> None:
    """
    Main entry point: load RBI data, build narrative chunks,
    embed them, and upsert into the database.
    """
    from vyom.store.repo import create_pool, Repository
    from vyom.providers import get_provider

    settings = settings or get_settings()
    provider = get_provider(settings)

    pool = await create_pool(settings)
    await pool.open()
    repo = Repository(pool)

    logger.info("Starting RBI ingest for %d series …", len(RBI_SERIES))

    for spec in RBI_SERIES:
        sid = spec["series_id"]

        # Upsert series metadata
        await repo.upsert_rbi_series(
            series_id=sid,
            title=spec["title"],
            category=spec["category"],
            frequency=spec["frequency"],
            units=spec["units"],
            notes=spec["description"],
        )

        # Get observations
        observations = HARDCODED_DATA.get(sid, [])
        if not observations:
            logger.warning("No data for series %s — skipping", sid)
            continue

        # Upsert raw observations
        await repo.upsert_rbi_observations(sid, observations)

        # Build narrative chunks
        narrative_chunks = _build_narrative(
            series_id=sid,
            title=spec["title"],
            description=spec["description"],
            category=spec["category"],
            units=spec["units"],
            observations=observations,
        )

        if not narrative_chunks:
            continue

        # Embed all chunks for this series
        texts      = [c["content"] for c in narrative_chunks]
        embeddings = provider.embed(texts)

        # Attach embeddings
        for chunk, emb in zip(narrative_chunks, embeddings, strict=False):
            chunk["embedding"] = emb

        # Upsert into rbi_chunks
        await repo.insert_rbi_chunks(narrative_chunks)
        logger.info("RBI %s: %d chunks ingested", sid, len(narrative_chunks))

    await pool.close()
    logger.info("RBI ingest complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        # psycopg's async pool requires a selector-based loop; asyncio.run()
        # defaults to ProactorEventLoop on Windows, which it explicitly rejects.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_rbi_ingest())