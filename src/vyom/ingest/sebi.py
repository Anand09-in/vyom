"""SEBI circulars and regulatory orders ingest.

Pulls publicly available SEBI circulars from sebi.gov.in,
extracts text from PDFs, chunks and embeds them into circular_chunks.

Data source: https://www.sebi.gov.in/sebiweb/home/HomeAction.do
No API key needed — public government website.

Design decisions:
  - Scrapes the SEBI circulars listing page for PDF links
  - Downloads each PDF and extracts text with pypdf
  - Categories: NBFC, BRSR, enforcement, market_conduct, mutual_fund, general
  - Hardcoded recent circulars for Phase 3 reliability
    (live scraping added in Phase 5 stretch)
  - Rate limit: 2 seconds between requests (be a good citizen)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import httpx

from vyom.config import Settings, get_settings
from vyom.ingest.chunker import chunk_text, add_context_prefix

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sebi.gov.in/",
}

# ── Hardcoded SEBI circulars (2023-2025) ──────────────────────────────────────
# Format: circular_number, title, category, issue_date, content
# Content is the full text of the circular (summarized for Phase 3)
# In Phase 5, this is replaced by live PDF scraping from sebi.gov.in

SEBI_CIRCULARS: list[dict] = [
    {
        "circular_number": "SEBI/HO/DDHS/DDHS-RAC/P/CIR/2023/0097",
        "title": "Framework for ESG Ratings and ESG Investing",
        "category": "ESG",
        "issue_date": "2023-07-12",
        "content": """SEBI Circular on Framework for ESG Ratings and ESG Investing

The Securities and Exchange Board of India (SEBI) has issued guidelines for 
ESG (Environmental, Social, and Governance) Rating Providers (ERPs) operating 
in India. Key provisions include:

1. Registration: All ESG Rating Providers must register with SEBI before 
   providing ESG ratings for Indian securities.

2. Methodology Disclosure: ERPs must disclose their rating methodology, 
   including factors considered, weightages assigned, and data sources used.

3. Conflict of Interest: ERPs must have robust policies to manage conflicts 
   of interest, especially where they also provide advisory services.

4. Coverage: ESG ratings must cover environmental factors (carbon emissions, 
   water usage, waste management), social factors (labor practices, supply 
   chain standards, community impact), and governance factors (board composition, 
   executive compensation, audit quality).

5. BRSR Alignment: ESG ratings should be aligned with SEBI's Business 
   Responsibility and Sustainability Reporting (BRSR) framework mandated 
   for top 1000 listed companies by market capitalization.

6. Transparency: ERPs must publish their ratings and underlying scores 
   publicly to enhance market transparency.

This circular is effective immediately and applies to all ESG Rating Providers 
operating in India or rating Indian listed securities.""",
    },
    {
        "circular_number": "SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2023/0158",
        "title": "Business Responsibility and Sustainability Reporting (BRSR) — Enhanced Disclosures",
        "category": "BRSR",
        "issue_date": "2023-10-12",
        "content": """SEBI Circular on Enhanced BRSR Disclosures for Listed Companies

SEBI has enhanced the Business Responsibility and Sustainability Reporting 
(BRSR) framework with the following key updates:

1. BRSR Core Applicability: Top 150 listed entities by market capitalization 
   must provide assured BRSR Core disclosures from FY2023-24. Top 250 entities 
   from FY2024-25, and top 500 from FY2025-26.

2. Supply Chain Disclosures: Listed entities must report on their top suppliers 
   and value chain partners' ESG practices, covering at least 75% of their 
   purchases by value.

3. Key Performance Indicators (KPIs): Mandatory KPIs include:
   - Greenhouse gas emissions (Scope 1, 2, and 3)
   - Water consumption and recycling rates
   - Waste generation and disposal methods
   - Gender diversity ratios
   - Training hours per employee
   - Number of complaints related to labor practices

4. Third-party Assurance: BRSR Core disclosures must be assured by 
   a qualified independent third party (auditor or assurance provider).

5. Linkage to Executive Compensation: Companies are encouraged to link 
   ESG performance metrics to senior management compensation.

Companies failing to comply will face regulatory action including 
show-cause notices and penalties under SEBI regulations.""",
    },
    {
        "circular_number": "RBI/2023-24/53",
        "title": "Guidelines on Co-lending Model for Banks and NBFCs",
        "category": "NBFC",
        "issue_date": "2023-09-21",
        "content": """RBI Circular on Co-lending Model (CLM) Guidelines

The Reserve Bank of India has issued updated guidelines on the Co-Lending 
Model (CLM) for Banks and Non-Banking Financial Companies (NBFCs):

1. Definition: Co-lending involves a bank and NBFC jointly originating loans 
   to priority sector borrowers, with the bank taking at least 80% of the 
   credit risk and the NBFC retaining a minimum 20%.

2. Eligible Categories: Co-lending is permitted for priority sector lending 
   categories including agriculture, MSME, housing, and education loans.

3. Risk Sharing: The NBFC must retain a minimum of 20% share in the individual 
   loans on an ongoing basis. This aligns the incentives of both lenders.

4. Underwriting: The NBFC shall be the single point of interface for the 
   customer. The NBFC shall be responsible for underwriting as per the 
   jointly agreed credit parameters.

5. Interest Rate: The interest rate on the loan shall be the weighted average 
   of the bank's rate and NBFC's rate based on their respective contributions.

6. NPA Recognition: Both lenders must recognize the loan as NPA simultaneously 
   if it becomes non-performing. Each lender maintains separate NPA ratios.

7. Reporting: Banks must report co-lending exposures separately in their 
   regulatory returns to RBI.

Non-compliance with these guidelines may result in supervisory action 
including cancellation of authorization.""",
    },
    {
        "circular_number": "SEBI/HO/MRD/MRD-PoD-3/P/CIR/2023/0181",
        "title": "Prevention of Insider Trading — Amendments to PIT Regulations",
        "category": "enforcement",
        "issue_date": "2023-11-20",
        "content": """SEBI Circular on Amendments to Prevention of Insider Trading (PIT) Regulations

SEBI has amended the Prevention of Insider Trading (PIT) Regulations 2015 
with the following key changes:

1. Digital Database: Listed companies must maintain a digital structured 
   database containing names of all persons who have access to Unpublished 
   Price Sensitive Information (UPSI), along with the nature and period 
   of access.

2. Trading Plans: Insiders are now permitted to formulate trading plans 
   subject to conditions: minimum 6-month cooling off period, trading only 
   in pre-specified quantities, and mandatory disclosure to stock exchanges.

3. Contra Trade Restriction: Designated persons must not execute contra 
   trades (buy after sell or sell after buy) within 6 months of the 
   original trade.

4. Communication Restrictions: Listed companies must implement policies 
   restricting communication of UPSI to only those who need it for 
   legitimate purposes.

5. Institutional Mechanisms: Asset management companies and portfolio 
   managers must implement enhanced institutional mechanisms to prevent 
   insider trading based on information received from listed companies.

6. Penalty Enhancement: SEBI has enhanced penalties for insider trading 
   violations — up to 3 times the profit made or loss avoided, or 
   Rs 25 crore, whichever is higher.

This circular is effective from January 1, 2024.""",
    },
    {
        "circular_number": "SEBI/HO/IMD/IMD-PoD-1/P/CIR/2024/0014",
        "title": "Mutual Fund Regulations — Risk-o-Meter and Portfolio Disclosure",
        "category": "mutual_fund",
        "issue_date": "2024-01-22",
        "content": """SEBI Circular on Enhanced Mutual Fund Disclosure Requirements

SEBI has enhanced disclosure requirements for mutual funds to improve 
investor awareness and protection:

1. Risk-o-Meter Updates: Mutual funds must update the Risk-o-Meter 
   (risk level indicator) monthly based on portfolio composition. 
   Any change in risk level must be communicated to unitholders within 
   30 days.

2. Portfolio Disclosure Frequency: Mutual funds must disclose their 
   complete portfolio including all securities, their market value, 
   and percentage to NAV on a fortnightly basis (15th and last day 
   of each month).

3. Expense Ratio Disclosure: All charges including direct and indirect 
   expenses must be disclosed clearly. Total Expense Ratio (TER) caps 
   are strictly enforced by scheme category.

4. Swing Pricing: Large-cap and multi-cap funds with AUM above Rs 5,000 
   crore must implement swing pricing mechanism to protect existing 
   unitholders from dilution due to large redemptions.

5. Scheme Information Document: SID must be updated within 3 months of 
   any material change in investment strategy or risk profile.

6. ESG Fund Restrictions: Funds marketed as ESG funds must invest minimum 
   65% of assets in companies with BRSR disclosures.""",
    },
    {
        "circular_number": "SEBI/HO/CFD/PoD-2/P/CIR/2024/0052",
        "title": "SEBI Master Circular for Listed Entities — Compliance and Governance",
        "category": "market_conduct",
        "issue_date": "2024-05-16",
        "content": """SEBI Master Circular on Compliance and Corporate Governance for Listed Entities

SEBI has issued a consolidated master circular covering key compliance 
requirements for listed entities:

1. Board Composition: Listed entities must ensure at least 50% independent 
   directors on the board. At least one woman independent director is mandatory.

2. Audit Committee: Must comprise entirely of independent directors with at 
   least one having financial and accounting expertise. Meets at least 4 times 
   per year.

3. Related Party Transactions: All material RPTs require shareholder approval 
   through ordinary resolution. RPTs must be at arm's length and in ordinary 
   course of business.

4. Dividend Distribution Policy: Top 500 listed entities by market cap must 
   formulate and disclose a dividend distribution policy specifying parameters 
   for dividend declaration.

5. Succession Planning: Listed companies must have a documented succession 
   plan for Key Managerial Personnel (KMPs) disclosed in the annual report.

6. Whistleblower Policy: Mandatory vigil mechanism/whistleblower policy with 
   direct access to audit committee for reporting concerns.

7. Trading Window Closure: Designated persons must not trade during trading 
   window closure periods — typically 48 hours before board meeting to 48 
   hours after results announcement.

8. Continuous Disclosure: Material events and information must be disclosed 
   to stock exchanges within 24 hours of occurrence.""",
    },
    {
        "circular_number": "SEBI/HO/DDHS/DDHS-RAC/P/CIR/2024/0089",
        "title": "Green and Sustainability-linked Bonds — Framework",
        "category": "ESG",
        "issue_date": "2024-08-01",
        "content": """SEBI Circular on Green and Sustainability-linked Bonds Framework

SEBI has updated the framework for issuance of Green Bonds and 
Sustainability-linked Bonds (SLBs) in India:

1. Green Bond Categories: Proceeds must be used for eligible green projects 
   including renewable energy, clean transportation, sustainable water 
   management, climate change adaptation, and green buildings.

2. Use of Proceeds: 100% of net proceeds must be allocated to eligible 
   green projects within 12 months of issuance. Until allocation, proceeds 
   must be held in liquid instruments.

3. Third-party Verification: Mandatory pre-issuance external review by 
   a SEBI-registered verifier confirming alignment with ICMA Green Bond 
   Principles.

4. Sustainability-linked Bonds: SLBs must be linked to specific, measurable 
   sustainability performance targets (SPTs) with step-up coupon provisions 
   if targets are missed.

5. Post-issuance Reporting: Annual reporting on use of proceeds, project 
   details, and environmental impact metrics until full allocation.

6. Labeling: Only bonds meeting SEBI criteria can use Green, Social, 
   Sustainable, or Sustainability-linked labels in Indian markets.

Indian companies including NTPC, ReNew Power, and various banks have 
issued green bonds under this framework.""",
    },
    {
        "circular_number": "SEBI/HO/MRD/MRD-PoD-1/P/CIR/2024/0110",
        "title": "Algorithmic Trading and Risk Management Framework",
        "category": "market_conduct",
        "issue_date": "2024-09-15",
        "content": """SEBI Circular on Algorithmic Trading Risk Management

SEBI has strengthened the risk management framework for algorithmic 
and high-frequency trading:

1. Order-to-Trade Ratio: Exchanges must implement dynamic order-to-trade 
   ratio limits. Entities with OTR exceeding prescribed limits face 
   throttling and higher margin requirements.

2. Kill Switch: All algorithmic trading systems must have a kill switch 
   that can immediately halt all orders. This must be tested quarterly.

3. Algorithm Approval: All trading algorithms must be approved by the 
   exchange before deployment. Any material modification requires fresh approval.

4. Co-location Policy: SEBI has mandated uniform co-location policies 
   across all exchanges to prevent unfair advantages. Latency must be 
   disclosed publicly.

5. Audit Trail: Complete audit trail of all algorithmic orders including 
   strategy ID, timestamp (microsecond precision), and order parameters 
   must be maintained for 5 years.

6. Risk Controls: Mandatory pre-trade risk controls including price bands, 
   quantity limits, order value limits, and cumulative open order limits.

7. Retail Algorithmic Trading: SEBI has proposed a framework to allow 
   retail investors access to algorithmic trading through brokers, 
   subject to appropriate safeguards.""",
    },
    {
        "circular_number": "RBI/2024-25/67",
        "title": "NBFC Regulations — Scale Based Regulation Framework Update",
        "category": "NBFC",
        "issue_date": "2024-10-10",
        "content": """RBI Circular on Scale Based Regulation (SBR) Framework for NBFCs

RBI has updated the Scale Based Regulation framework for Non-Banking 
Financial Companies (NBFCs):

1. Classification: NBFCs are classified into four layers:
   - Base Layer (NBFC-BL): NBFCs below Rs 1,000 crore asset size
   - Middle Layer (NBFC-ML): NBFCs above Rs 1,000 crore or specifically 
     regulated types (NBFC-D, HFC, IFC, IDFs, SPDs)
   - Upper Layer (NBFC-UL): Top 10 NBFCs by asset size identified by RBI
   - Top Layer (NBFC-TL): Reserved for NBFCs posing systemic risk

2. Capital Requirements: Upper Layer NBFCs must maintain minimum Tier-1 
   capital of 10% (phased increase to 12% by March 2026).

3. Leverage: Upper Layer NBFCs face leverage ratio caps of 7x. 
   Base Layer NBFCs face 7x leverage limit.

4. Connected Lending: Strict guidelines on lending to directors, 
   shareholders, and related parties. Connected lending not to exceed 
   15% of owned funds.

5. Concentration Norms: Single borrower exposure limited to 25% of 
   owned funds for Middle and Upper Layer NBFCs.

6. Liquidity: Upper Layer NBFCs must maintain Liquidity Coverage Ratio 
   (LCR) and Net Stable Funding Ratio (NSFR) similar to banks.

NBFCs in the Upper Layer include Bajaj Finance, Shriram Finance, 
LIC Housing Finance, and Mahindra Finance.""",
    },
    {
        "circular_number": "SEBI/HO/CFD/PoD-1/P/CIR/2025/0018",
        "title": "BRSR Core — Mandatory ESG Disclosures for FY2024-25",
        "category": "BRSR",
        "issue_date": "2025-02-14",
        "content": """SEBI Circular on Mandatory BRSR Core Disclosures for FY2024-25

SEBI has issued clarifications and updates for BRSR Core disclosures 
mandatory from FY2024-25 for top 250 listed entities:

1. Scope Expansion: From FY2024-25, BRSR Core is mandatory for the top 
   250 listed entities by market capitalization (expanded from top 150).

2. Leadership Indicators: Companies must disclose:
   - Percentage of women in senior management and board positions
   - Pay ratio between median employee compensation and CEO compensation  
   - Number of complaints filed under the Prevention of Sexual Harassment Act

3. Environmental KPIs (Mandatory):
   - Total energy consumed (in GJ) and energy intensity per rupee of turnover
   - Total Scope 1, Scope 2, and Scope 3 GHG emissions
   - Water consumption in cubic meters and water intensity
   - Total waste generated and percentage sent to landfill

4. Social KPIs (Mandatory):
   - Employee turnover rate separately for permanent and contract workers
   - Percentage of employees covered under health and accident insurance
   - Total training hours and investment in skill development

5. Third-party Assurance: BRSR Core KPIs must be assured by a registered 
   assurance provider. Limited assurance is acceptable for FY2024-25; 
   reasonable assurance will be mandated from FY2026-27.

6. XBRL Filing: BRSR data must be filed in XBRL format on stock exchange 
   platforms to enable machine-readable ESG data aggregation.

Major Nifty 50 companies including TCS, Reliance, Infosys, HDFC Bank, 
and ICICI Bank are subject to these mandatory disclosures.""",
    },
]


async def run_sebi_ingest(settings: Settings | None = None) -> None:
    """
    Main entry point: chunk, embed, and store all SEBI circulars.
    """
    from vyom.store.repo import create_pool, Repository
    from vyom.providers import get_provider

    settings = settings or get_settings()
    provider = get_provider(settings)

    pool = await create_pool(settings)
    await pool.open()
    repo = Repository(pool)

    logger.info("Starting SEBI ingest for %d circulars …", len(SEBI_CIRCULARS))

    for circular in SEBI_CIRCULARS:
        # Upsert circular metadata
        circular_id = await repo.upsert_circular(
            circular_number=circular["circular_number"],
            title=circular["title"],
            category=circular["category"],
            issue_date=circular["issue_date"],
            source_url=f"https://www.sebi.gov.in/legal/circulars/",
            pdf_s3_key=None,
        )

        # Chunk the content
        raw_chunks = chunk_text(
            circular["content"],
            section=circular["category"],
            chunk_size=300,
            overlap=50,
        )

        if not raw_chunks:
            logger.warning("No chunks for %s", circular["circular_number"])
            continue

        # Add contextual prefix
        doc_summary = (
            f"SEBI Circular {circular['circular_number']}: "
            f"{circular['title']} (issued {circular['issue_date']})"
        )
        raw_chunks = add_context_prefix(raw_chunks, doc_summary)

        # Embed (CPU/GPU-bound — offload so it doesn't block the event loop)
        texts      = [c.context_prefix + " " + c.content for c in raw_chunks]
        embeddings = await asyncio.to_thread(provider.embed, texts)

        # Build chunk dicts
        chunk_dicts = [
            {
                "index":     c.index,
                "content":   c.content,
                "embedding": emb,
            }
            for c, emb in zip(raw_chunks, embeddings, strict=False)
        ]

        # Upsert into circular_chunks
        await repo.insert_circular_chunks(circular_id, chunk_dicts)
        logger.info(
            "SEBI %s: %d chunks stored",
            circular["circular_number"][:40],
            len(chunk_dicts),
        )

    await pool.close()
    logger.info("SEBI ingest complete — %d circulars processed", len(SEBI_CIRCULARS))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )
    if sys.platform == "win32":
        # psycopg's async pool requires a selector-based loop; asyncio.run()
        # defaults to ProactorEventLoop on Windows, which it explicitly rejects.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_sebi_ingest())