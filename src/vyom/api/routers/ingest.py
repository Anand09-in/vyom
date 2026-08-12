"""POST /ingest/* — trigger data ingestion jobs as background tasks.

Each endpoint queues the job and returns immediately (202 Accepted).
The actual work runs in the background via FastAPI BackgroundTasks.

Endpoints:
  POST /ingest/bse    — pull BSE annual reports for Nifty 50
  POST /ingest/sebi   — scrape SEBI circulars
  POST /ingest/rbi    — download RBI DBIE macro CSVs
  POST /ingest/all    — trigger all three at once
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from vyom.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# Default Nifty 50 company list
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "HINDUNILVR", "LT", "ITC",
    "KOTAKBANK", "BAJFINANCE", "HCLTECH", "WIPRO", "AXISBANK",
    "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "POWERGRID", "NTPC", "BAJAJFINSV", "TECHM", "NESTLEIND",
    "ONGC", "TATAMOTORS", "ADANIENT", "JSWSTEEL", "COALINDIA",
    "DRREDDY", "DIVISLAB", "HINDALCO", "CIPLA", "BPCL",
    "TATACONSUM", "EICHERMOT", "M&M", "APOLLOHOSP", "GRASIM",
    "INDUSINDBK", "BRITANNIA", "HEROMOTOCO", "SBILIFE", "BEL",
    "TRENT", "BAJAJ-AUTO", "SHRIRAMFIN", "ADANIPORTS", "HDFCLIFE",
]


class IngestRequest(BaseModel):
    companies: list[str] | None = None   # defaults to full Nifty 50


class IngestResponse(BaseModel):
    status: str
    source: str
    companies: list[str] | None = None


def _run_bse(companies: list[str], settings) -> None:
    """Placeholder — implemented in Phase 1 (ingest/bse.py)."""
    logger.info("BSE ingest queued for %d companies", len(companies))


def _run_sebi(settings) -> None:
    """Placeholder — implemented in Phase 3 (ingest/sebi.py)."""
    logger.info("SEBI ingest queued")


def _run_rbi(settings) -> None:
    """Placeholder — implemented in Phase 1 (ingest/rbi.py)."""
    logger.info("RBI ingest queued")


@router.post("/bse", response_model=IngestResponse, status_code=202)
async def ingest_bse(req: IngestRequest, bg: BackgroundTasks) -> IngestResponse:
    companies = req.companies or NIFTY_50
    bg.add_task(_run_bse, companies, get_settings())
    return IngestResponse(status="queued", source="bse", companies=companies)


@router.post("/sebi", response_model=IngestResponse, status_code=202)
async def ingest_sebi(bg: BackgroundTasks) -> IngestResponse:
    bg.add_task(_run_sebi, get_settings())
    return IngestResponse(status="queued", source="sebi")


@router.post("/rbi", response_model=IngestResponse, status_code=202)
async def ingest_rbi(bg: BackgroundTasks) -> IngestResponse:
    bg.add_task(_run_rbi, get_settings())
    return IngestResponse(status="queued", source="rbi")


@router.post("/all", response_model=IngestResponse, status_code=202)
async def ingest_all(req: IngestRequest, bg: BackgroundTasks) -> IngestResponse:
    companies = req.companies or NIFTY_50
    settings = get_settings()
    bg.add_task(_run_bse, companies, settings)
    bg.add_task(_run_sebi, settings)
    bg.add_task(_run_rbi, settings)
    return IngestResponse(status="queued", source="all", companies=companies)