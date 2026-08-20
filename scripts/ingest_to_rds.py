"""Run ingestion locally, save the results to AWS RDS instead of local Docker
Postgres — the manual, no-scheduling-no-AWS-pipeline path decided for
Phase 2 of the platform roadmap.

Nothing about *how* ingestion works changes: same local embedding/reranking
models, same machine, same `run_bse_ingest()`/`run_sebi_ingest()`/
`run_rbi_ingest()` functions used for local ingestion. The only thing this
script does differently is point `Settings.database_url` at RDS instead of
reading local `.env` — local Docker Postgres and `.env` are untouched.

Safe to re-run: Repository.filing_exists() (BSE only — see bse.py) skips
already-ingested filings instead of redoing the expensive download/extract/
embed path, so this is incremental, not a full redo every time.

Usage:
    python scripts/ingest_to_rds.py --database-url postgresql://vyom:PASSWORD@vyom-db.xxxx.ap-south-1.rds.amazonaws.com:5432/vyom
    python scripts/ingest_to_rds.py --database-url ... --source bse --companies RELIANCE TCS

Get the RDS connection string via `terraform output -raw rds_database_url`
in infra/ (make sure `CREATE EXTENSION vector;` and schema.sql have already
been applied to that database — see infra/main.tf's Phase 2 notes).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest locally, save to AWS RDS")
    parser.add_argument(
        "--database-url", required=True,
        help="RDS Postgres connection string (terraform output -raw rds_database_url in infra/)",
    )
    parser.add_argument("--source", choices=["bse", "sebi", "rbi", "all"], default="all")
    parser.add_argument(
        "--companies", nargs="*", default=None,
        help="BSE tickers to ingest, e.g. RELIANCE TCS. Defaults to the full Nifty 100.",
    )
    args = parser.parse_args()

    from vyom.config import Settings
    settings = Settings(database_url=args.database_url)

    if args.source in ("bse", "all"):
        from vyom.ingest.bse import NIFTY_100, run_bse_ingest

        companies = None
        if args.companies:
            wanted = set(args.companies)
            companies = [c for c in NIFTY_100 if c[2] in wanted]
            missing = wanted - {c[2] for c in companies}
            if missing:
                logger.warning("Unknown tickers, skipping: %s", ", ".join(sorted(missing)))
        await run_bse_ingest(companies=companies, settings=settings)

    if args.source in ("sebi", "all"):
        from vyom.ingest.sebi import run_sebi_ingest
        await run_sebi_ingest(settings=settings)

    if args.source in ("rbi", "all"):
        from vyom.ingest.rbi import run_rbi_ingest
        await run_rbi_ingest(settings=settings)


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg's async pool requires a selector-based loop; asyncio.run()
        # defaults to ProactorEventLoop on Windows, which it explicitly rejects.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
