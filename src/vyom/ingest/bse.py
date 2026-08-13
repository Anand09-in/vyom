"""BSE annual report ingest.

Pulls the latest annual report PDF for each Nifty 50 company from BSE,
extracts text, chunks it, embeds it, and stores it in filing_chunks.

Flow:
  BSE API → company scrip code → annual report PDF URL
  → download PDF → extract text with pypdf
  → chunk (512 words, 64 overlap) + contextual prefix
  → embed with BGE-M3 → upsert into filings + filing_chunks

Design decisions:
  - pypdf for PDF parsing (pure Python, no external binaries needed on Windows)
  - 512-word chunks with 64-word overlap (standard for financial documents)
  - Contextual prefix on every chunk so it retrieves well in isolation
  - Upsert is idempotent — safe to re-run
  - Rate limiting: 1 second between BSE requests (be a good citizen)
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

import httpx

from vyom.config import Settings, get_settings
from vyom.ingest.chunker import chunk_text, add_context_prefix

logger = logging.getLogger(__name__)

# ── Nifty 50 companies with BSE scrip codes ────────────────────────────────────
# Format: (company_name, bse_scrip_code, nse_symbol)
NIFTY_50: list[tuple[str, str, str]] = [
    ("Reliance Industries",          "500325", "RELIANCE"),
    ("Tata Consultancy Services",    "532540", "TCS"),
    ("HDFC Bank",                    "500180", "HDFCBANK"),
    ("Bharti Airtel",                "532454", "BHARTIARTL"),
    ("ICICI Bank",                   "532174", "ICICIBANK"),
    ("Infosys",                      "500209", "INFY"),
    ("State Bank of India",          "500112", "SBIN"),
    ("Hindustan Unilever",           "500696", "HINDUNILVR"),
    ("Larsen & Toubro",              "500510", "LT"),
    ("ITC",                          "500875", "ITC"),
    ("Kotak Mahindra Bank",          "500247", "KOTAKBANK"),
    ("Bajaj Finance",                "500034", "BAJFINANCE"),
    ("HCL Technologies",             "532281", "HCLTECH"),
    ("Wipro",                        "507685", "WIPRO"),
    ("Axis Bank",                    "532215", "AXISBANK"),
    ("Asian Paints",                 "500820", "ASIANPAINT"),
    ("Maruti Suzuki",                "532500", "MARUTI"),
    ("Sun Pharmaceutical",           "524715", "SUNPHARMA"),
    ("Titan Company",                "500114", "TITAN"),
    ("UltraTech Cement",             "532538", "ULTRACEMCO"),
    ("Power Grid Corporation",       "532898", "POWERGRID"),
    ("NTPC",                         "532555", "NTPC"),
    ("Bajaj Finserv",                "532978", "BAJAJFINSV"),
    ("Tech Mahindra",                "532755", "TECHM"),
    ("Nestle India",                 "500790", "NESTLEIND"),
    ("ONGC",                         "500312", "ONGC"),
    ("Tata Motors",                  "500570", "TATAMOTORS"),
    ("Adani Enterprises",            "512599", "ADANIENT"),
    ("JSW Steel",                    "500228", "JSWSTEEL"),
    ("Coal India",                   "533278", "COALINDIA"),
    ("Dr Reddy's Laboratories",      "500124", "DRREDDY"),
    ("Divi's Laboratories",          "532488", "DIVISLAB"),
    ("Hindalco Industries",          "500440", "HINDALCO"),
    ("Cipla",                        "500087", "CIPLA"),
    ("BPCL",                         "500547", "BPCL"),
    ("Tata Consumer Products",       "500800", "TATACONSUM"),
    ("Eicher Motors",                "505200", "EICHERMOT"),
    ("Mahindra & Mahindra",          "500520", "M&M"),
    ("Apollo Hospitals",             "508869", "APOLLOHOSP"),
    ("Grasim Industries",            "500300", "GRASIM"),
    ("IndusInd Bank",                "532187", "INDUSINDBK"),
    ("Britannia Industries",         "500825", "BRITANNIA"),
    ("Hero MotoCorp",                "500182", "HEROMOTOCO"),
    ("SBI Life Insurance",           "540719", "SBILIFE"),
    ("Bharat Electronics",           "500049", "BEL"),
    ("Trent",                        "500251", "TRENT"),
    ("Bajaj Auto",                   "532977", "BAJAJ-AUTO"),
    ("Shriram Finance",              "511218", "SHRIRAMFIN"),
    ("Adani Ports",                  "532921", "ADANIPORTS"),
    ("HDFC Life Insurance",          "540777", "HDFCLIFE"),
]

# BSE API base URL for corporate filings
BSE_ANNUALREPORT_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w"
    "?scripcode={scrip_code}&type=Company"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
}


_UUID_PDF_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf",
    re.IGNORECASE,
)


def _build_report_pdf_url(scrip_code: str, file_name: str) -> str:
    """
    Turn a BSE AnnualReport API `file_name` into a downloadable PDF URL.

    BSE has two eras of filenames, each served from a different path:
      - Modern (~2023+): a UUID with a doubled ".pdf.pdf" suffix (some
        entries also carry a stray leading "\\" — a BSE data-quality
        artifact), served from the corp-filing attachment store.
      - Legacy: a short numeric filename (e.g. "73256500180.pdf"), served
        under bseplus/AnnualReport/<scripcode>/.
    Neither field is a URL on its own — both require reconstructing the
    real host path, which differs by era.
    """
    file_name = file_name.lstrip("\\/")

    if _UUID_PDF_RE.match(file_name):
        uuid_part = file_name.split(".pdf")[0]
        return f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{uuid_part}.pdf"

    return f"https://www.bseindia.com/bseplus/AnnualReport/{scrip_code}/{file_name}"


async def _get_annual_report_url(
    scrip_code: str,
    company_name: str,
    client: httpx.AsyncClient,
) -> str | None:
    """Fetch the latest annual report PDF URL from BSE API."""
    try:
        url = BSE_ANNUALREPORT_URL.format(scrip_code=scrip_code)
        resp = await client.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # BSE returns a list of annual report entries, newest year first
        reports = data if isinstance(data, list) else data.get("Table", [])
        if not reports:
            logger.warning("%s: no annual reports found", company_name)
            return None

        file_name = (reports[0].get("file_name") or "").strip()
        if not file_name:
            logger.warning("%s: report entry has no file_name", company_name)
            return None

        return _build_report_pdf_url(scrip_code, file_name)

    except Exception as exc:
        logger.error("%s: failed to get report URL — %s", company_name, exc)
        return None


def _extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file using pypdf."""
    import pypdf

    text_parts: list[str] = []
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    except Exception as exc:
        logger.error("PDF extraction failed for %s: %s", pdf_path, exc)

    return "\n".join(text_parts)


def _classify_section(text_chunk: str) -> str:
    """Heuristic: classify a chunk into a filing section based on keywords."""
    text_lower = text_chunk.lower()
    if any(k in text_lower for k in ["management discussion", "mda", "md&a"]):
        return "mda"
    if any(k in text_lower for k in ["risk factor", "risk management", "key risk"]):
        return "risk_factors"
    if any(k in text_lower for k in ["balance sheet", "profit and loss", "cash flow", "financial statement"]):
        return "financials"
    if any(k in text_lower for k in ["director", "board", "governance", "csr"]):
        return "governance"
    if any(k in text_lower for k in ["chairman", "dear shareholder", "letter to"]):
        return "chairman_letter"
    return "general"


async def _ingest_one_company(
    company_name: str,
    scrip_code: str,
    nse_symbol: str,
    repo,
    provider,
    settings: Settings,
    client: httpx.AsyncClient,
) -> int:
    """Download, parse, chunk, embed, and store one company's annual report."""

    # Step 1: get PDF URL
    pdf_url = await _get_annual_report_url(scrip_code, company_name, client)
    if not pdf_url:
        logger.warning("%s: skipping — no PDF URL found", company_name)
        return 0

    logger.info("%s: downloading from %s", company_name, pdf_url[:80])

    # Step 2: download PDF
    download_dir = Path(settings.bse_download_folder)
    download_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = download_dir / f"{nse_symbol}_annual_report.pdf"

    try:
        async with client.stream("GET", pdf_url, headers=HEADERS, timeout=120) as resp:
            resp.raise_for_status()
            with open(pdf_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
    except Exception as exc:
        logger.error("%s: PDF download failed — %s", company_name, exc)
        return 0

    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    logger.info("%s: downloaded %.1f MB", company_name, file_size_mb)

    # Step 3: extract text (CPU-bound — offload so it doesn't block the loop)
    raw_text = await asyncio.to_thread(_extract_text_from_pdf, pdf_path)
    if len(raw_text.strip()) < 500:
        logger.warning("%s: extracted text too short (%d chars) — PDF may be scanned/image-based",
                       company_name, len(raw_text))
        return 0

    logger.info("%s: extracted %d characters", company_name, len(raw_text))

    # Step 4: upsert filing record
    from datetime import date
    filing_id = await repo.upsert_filing(
        company_name=company_name,
        bse_code=scrip_code,
        nse_symbol=nse_symbol,
        filing_type="annual_report",
        filing_date=str(date.today()),
        source_url=pdf_url,
        pdf_s3_key=None,  # S3 upload added in Phase 4
    )

    # Step 5: chunk the text
    raw_chunks = chunk_text(raw_text, section="general", chunk_size=512, overlap=64)

    # Classify each chunk into a section
    for chunk in raw_chunks:
        chunk.section = _classify_section(chunk.content)

    # Add contextual prefix
    doc_summary = f"{company_name} Annual Report {date.today().year}"
    raw_chunks = add_context_prefix(raw_chunks, doc_summary)

    if not raw_chunks:
        logger.warning("%s: no chunks generated", company_name)
        return 0

    logger.info("%s: %d chunks created", company_name, len(raw_chunks))

    # Step 6: embed in batches of 16 (avoid OOM on local BGE-M3)
    BATCH_SIZE = 16
    all_chunks_with_embeddings: list[dict] = []

    for i in range(0, len(raw_chunks), BATCH_SIZE):
        batch = raw_chunks[i : i + BATCH_SIZE]
        texts = [c.context_prefix + " " + c.content for c in batch]
        # provider.embed() is a synchronous, CPU-bound call — running it inline
        # would block the event loop for minutes on a full annual report and
        # starve the async DB pool's own background connection tasks.
        embeddings = await asyncio.to_thread(provider.embed, texts)
        for chunk, emb in zip(batch, embeddings, strict=False):
            all_chunks_with_embeddings.append({
                "section":        chunk.section,
                "index":          chunk.index,
                "content":        chunk.content,
                "context_prefix": chunk.context_prefix,
                "embedding":      emb,
            })

    # Step 7: upsert chunks into database
    await repo.insert_filing_chunks(filing_id, all_chunks_with_embeddings)
    logger.info("%s: %d chunks stored in pgvector", company_name, len(all_chunks_with_embeddings))

    return len(all_chunks_with_embeddings)


async def run_bse_ingest(
    companies: list[tuple[str, str, str]] | None = None,
    settings: Settings | None = None,
) -> None:
    """
    Main entry point: ingest annual reports for all specified companies.

    Args:
        companies: List of (company_name, bse_scrip_code, nse_symbol).
                   Defaults to full Nifty 50.
        settings:  Config object. Defaults to get_settings().
    """
    from vyom.store.repo import create_pool, Repository
    from vyom.providers import get_provider

    settings  = settings or get_settings()
    provider  = get_provider(settings)
    companies = companies or NIFTY_50

    pool = await create_pool(settings)
    await pool.open()
    repo = Repository(pool)

    total_chunks = 0
    failed: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for company_name, scrip_code, nse_symbol in companies:
            try:
                n = await _ingest_one_company(
                    company_name=company_name,
                    scrip_code=scrip_code,
                    nse_symbol=nse_symbol,
                    repo=repo,
                    provider=provider,
                    settings=settings,
                    client=client,
                )
                total_chunks += n
            except Exception as exc:
                logger.error("%s: unexpected error — %s", company_name, exc)
                failed.append(company_name)

            # Rate limit: 1 second between companies
            await asyncio.sleep(1)

    await pool.close()

    logger.info("BSE ingest complete: %d total chunks across %d companies",
                total_chunks, len(companies) - len(failed))
    if failed:
        logger.warning("Failed companies: %s", ", ".join(failed))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )
    if sys.platform == "win32":
        # psycopg's async pool requires a selector-based loop; asyncio.run()
        # defaults to ProactorEventLoop on Windows, which it explicitly rejects.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_bse_ingest())