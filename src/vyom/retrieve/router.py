"""Vyom source router — classifies a query to one or more data sources.

Design decision: rule-based keyword matching, NOT an LLM call.
Reason: Indian financial vocabulary is finite and well-defined.
        A regex classifier is deterministic, free, and adds zero latency.
        An LLM router would cost ~500 tokens per query and add 1-2 seconds.

Four possible route targets:
  bse   — BSE/NSE corporate filings (annual reports, quarterly results)
  sebi  — SEBI regulatory circulars and enforcement orders
  rbi   — RBI macro data (repo rate, CPI, credit growth, forex)
  cross — requires combining two or more sources

The RouteDecision also carries a human-readable rationale that is surfaced
in the API response — useful for demos and for debugging bad routing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RouteDecision:
    sources: list[str]          # ordered by relevance, e.g. ['bse', 'rbi']
    rationale: str              # shown in API response, good for demos


# ── Signal pattern lists ───────────────────────────────────────────────────────
# Each list contains regex patterns. A query scores +1 for each match.
# The source with the highest score wins. Ties go to 'cross'.

_BSE_SIGNALS = [
    r"\bannual report\b",
    r"\bquarterly result\b",
    r"\bbalance sheet\b",
    r"\bprofit.{0,10}loss\b",
    r"\brevenue\b",
    r"\bebitda\b",
    r"\bpat\b",
    r"\beps\b",
    r"\bnet profit\b",
    r"\bmarket cap\b",
    r"\bdividend\b",
    r"\bcapex\b",
    r"\bdebt\b",
    r"\bnpa\b",
    r"\bgnpa\b",
    r"\bnnpa\b",
    r"\bnim\b",
    r"\bcasa\b",
    r"\bloan book\b",
    r"\basset quality\b",
    r"\bmanagement discussion\b",
    r"\brisk factor\b",
    r"\bboard of director\b",
    r"\bshareholder\b",
    r"\bipo\b",
    r"\bfii\b",
    r"\bdii\b",
    r"\bpromoter\b",
    r"\breliance\b",
    r"\btcs\b",
    r"\binfosys\b",
    r"\bhdfc\b",
    r"\bicici\b",
    r"\bsbi\b",
    r"\bwipro\b",
    r"\bhcl\b",
    r"\bbajaj\b",
    r"\baxis bank\b",
    r"\bkotak\b",
    r"\bnifty\b",
    r"\bsensex\b",
    r"\bbse\b",
    r"\bnse\b",
    r"\bfiling\b",
]

_SEBI_SIGNALS = [
    r"\bsebi\b",
    r"\bcircular\b",
    r"\bregulat\w+\b",
    r"\bcompliance\b",
    r"\bdisclosure\b",
    r"\bbrsr\b",
    r"\besg\b",
    r"\bsustainabilit\w+\b",
    r"\bnbfc\b",
    r"\bco.lending\b",
    r"\bmutual fund\b",
    r"\bstock exchange\b",
    r"\binsider trading\b",
    r"\benforcement\b",
    r"\bpenalt\w+\b",
    r"\border\b",
    r"\baif\b",
    r"\bpms\b",
    r"\bfpi\b",
    r"\bderivative\b",
    r"\boption\b",
    r"\bfuture\b",
    r"\bdemat\b",
    r"\bdepository\b",
    r"\bkyc\b",
    r"\banti.money laundering\b",
    r"\baml\b",
]

_RBI_SIGNALS = [
    r"\brbi\b",
    r"\brepo rate\b",
    r"\breverse repo\b",
    r"\bmonetary policy\b",
    r"\bmpc\b",
    r"\binflation\b",
    r"\bcpi\b",
    r"\bwpi\b",
    r"\bgdp\b",
    r"\biip\b",
    r"\bcredit growth\b",
    r"\bmoney supply\b",
    r"\bm3\b",
    r"\bcrr\b",
    r"\bslr\b",
    r"\bforex\b",
    r"\bforeign exchange\b",
    r"\binr\b",
    r"\brupee\b",
    r"\bfx\b",
    r"\busd.inr\b",
    r"\bcurrency\b",
    r"\bcurrent account\b",
    r"\btrade deficit\b",
    r"\bcad\b",
    r"\bfiscal deficit\b",
    r"\bbond yield\b",
    r"\bg.sec\b",
    r"\btreasury\b",
    r"\bliquidity\b",
    r"\bopen market operation\b",
    r"\bomo\b",
    r"\bbase rate\b",
    r"\bmclr\b",
    r"\bcredit offtake\b",
    r"\bbank credit\b",
    r"\bnon.performing\b",
    r"\bprovision\b",
    r"\bcapital adequacy\b",
    r"\bcrar\b",
    r"\bdbie\b",
]

_CROSS_TRIGGERS = [
    # Filing + macro
    r"(npa|loan|credit).{0,60}(repo|rate|rbi|inflation|monetary)",
    r"(repo|rate|rbi|inflation).{0,60}(npa|loan|bank|hdfc|icici|sbi)",
    # Filing + regulatory
    r"(annual report|filing|result).{0,60}(sebi|circular|complian|brsr)",
    r"(sebi|circular|complian).{0,60}(annual report|filing|company)",
    # Regulatory + macro
    r"(nbfc|co.lending).{0,60}(repo|rbi|monetary|inflation)",
    r"(rbi|monetary|repo).{0,60}(nbfc|circular|sebi|complian)",
    # Explicit combination language
    r"\bgiven.{0,40}(annual|filing|report|npa).{0,40}(rbi|sebi|rate|inflation)\b",
    r"\bhow does.{0,40}(rate|inflation|rbi).{0,40}(affect|impact).{0,40}(bank|company)\b",
    r"\bcompare\b",
    r"\bcross.source\b",
    r"\ball three\b",
    r"\bboth.{0,20}(rbi|sebi|bse)\b",
]


def _count_hits(text: str, patterns: list[str]) -> int:
    """Count how many patterns match the lowercased query text."""
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))


def route(
    query: str,
    enabled_sources: list[str] | None = None,
) -> RouteDecision:
    """
    Classify a query and return which source(s) to retrieve from.

    Args:
        query:           The user's natural language question.
        enabled_sources: Which sources are available. Defaults to all four.

    Returns:
        RouteDecision with a list of sources and a human-readable rationale.
    """
    enabled = set(enabled_sources or ["bse", "sebi", "rbi", "cross"])

    cross_hits = _count_hits(query, _CROSS_TRIGGERS)
    bse_hits   = _count_hits(query, _BSE_SIGNALS)
    sebi_hits  = _count_hits(query, _SEBI_SIGNALS)
    rbi_hits   = _count_hits(query, _RBI_SIGNALS)

    per_source_hits = {"bse": bse_hits, "sebi": sebi_hits, "rbi": rbi_hits}
    sources_with_signal = [s for s, hits in per_source_hits.items() if hits > 0]

    # ── Cross-source: explicit trigger phrase OR real signal from 2+ sources ──
    # Two distinct ways a query can be cross-source:
    #  1. An explicit _CROSS_TRIGGERS phrase matches (e.g. "repo rate...
    #     impact on bank margins"). These patterns are written to imply two
    #     source categories by construction even when generic words like
    #     "bank"/"margins" aren't themselves in the per-source keyword lists
    #     — so search all three sources, since we can't cheaply tell which
    #     two the trigger meant.
    #  2. No trigger phrase matches, but the query independently contains
    #     real signal words from 2+ distinct source categories (e.g. names
    #     both "Reliance" and "RBI"). The _CROSS_TRIGGERS patterns require
    #     specific word order/proximity and miss many legitimate phrasings
    #     — this catches those without over-triggering on ordinary
    #     single-source queries that only ever hit one category.
    if cross_hits > 0 and "cross" in enabled:
        sources = [s for s in ("bse", "sebi", "rbi") if s in enabled] or ["bse"]
        return RouteDecision(
            sources=sources,
            rationale=(
                f"Cross-source query detected — pulling from "
                f"{' + '.join(s.upper() for s in sources)}"
            ),
        )

    if len(sources_with_signal) >= 2 and "cross" in enabled:
        sources = [s for s in sources_with_signal if s in enabled] or ["bse"]
        return RouteDecision(
            sources=sources,
            rationale=(
                f"Cross-source query detected — pulling from "
                f"{' + '.join(s.upper() for s in sources)}"
            ),
        )

    # ── Single-source: highest signal wins ────────────────────────────────────
    scores: dict[str, int] = {}
    if "bse"  in enabled: scores["bse"]  = bse_hits
    if "sebi" in enabled: scores["sebi"] = sebi_hits
    if "rbi"  in enabled: scores["rbi"]  = rbi_hits

    if not scores:
        return RouteDecision(sources=["bse"], rationale="No sources enabled — defaulting to BSE")

    best_source = max(scores, key=lambda k: scores[k])
    best_score  = scores[best_source]

    # ── No signal matched — default to BSE + RBI (broad useful default) ───────
    if best_score == 0:
        fallback = [s for s in ["bse", "rbi"] if s in enabled]
        return RouteDecision(
            sources=fallback,
            rationale="General query — searching BSE filings and RBI macro context",
        )

    return RouteDecision(
        sources=[best_source],
        rationale=(
            f"Routed to {best_source.upper()} "
            f"({best_score} signal {'match' if best_score == 1 else 'matches'})"
        ),
    )