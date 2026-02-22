"""SEC EDGAR tools — full-text search, NPORT-P holdings parsing, and filing section extraction."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

import httpx

import tools.edgar_client as _edgar_init  # noqa: F401 — triggers set_identity()
from edgar import Company, find as edgar_find

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_data import AsyncFMPDataClient

logger = logging.getLogger(__name__)

EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_USER_AGENT = os.environ.get("EDGAR_USER_AGENT", "")
EDGAR_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

OPENAI_API_KEY = os.environ.get("OPENAI_KEY", "")
OPENAI_MODEL = "gpt-4.1-mini"

# Max filings to parse holdings for (each involves SEC fetch + XML parse)
_MAX_PARSE_FILINGS = 5

# Section key mapping for 10-K filings (friendly name -> edgartools key)
_TENK_SECTIONS = {
    "business": "business",
    "risk_factors": "risk_factors",
    "mda": "mda",
    "financials": "financial_statements",
    "legal": "legal_proceedings",
    "properties": "properties",
    "cybersecurity": "cybersecurity",
    "executive_compensation": "executive_compensation",
}

# Section key mapping for 10-Q filings
_TENQ_SECTIONS = {
    "financials": "Part I, Item 1",
    "mda": "Part I, Item 2",
    "market_risk": "Part I, Item 3",
    "controls": "Part I, Item 4",
    "legal": "Part II, Item 1",
    "risk_factors": "Part II, Item 1A",
}


async def _edgar_search(
    query: str,
    forms: str | None,
    start_date: str | None,
    end_date: str | None,
    entity: str | None,
    limit: int,
) -> dict | None:
    """Execute EFTS search and return raw JSON."""
    params: dict[str, str | int] = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": start_date or (date.today() - timedelta(days=730)).isoformat(),
        "enddt": end_date or date.today().isoformat(),
    }
    if forms:
        params["forms"] = forms
    if entity:
        params["entity"] = entity
    # EFTS caps at 100 per page
    params["from"] = 0
    params["size"] = min(limit, 100)

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                EDGAR_EFTS_URL,
                params=params,
                headers={"User-Agent": EDGAR_USER_AGENT},
            )
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _build_filing_url(cik: str, accession: str) -> str:
    """Build SEC EDGAR filing URL from CIK and accession number."""
    cik_clean = cik.lstrip("0") or "0"
    accession_clean = accession.replace("-", "")
    return f"{EDGAR_ARCHIVES_BASE}/{cik_clean}/{accession_clean}/{accession}-index.htm"


_ENTITY_PATTERN = re.compile(
    r"^(.+?)\s*(?:\(([A-Z0-9.]+)\))?\s*\(CIK\s+([\d]+)\)\s*$"
)


def _parse_entity(display_name: str) -> tuple[str, str, str | None]:
    """Parse EFTS entity display name into (name, cik, ticker)."""
    m = _ENTITY_PATTERN.match(display_name.strip())
    if m:
        return m.group(1).strip(), m.group(3).zfill(10), m.group(2)
    return display_name.strip(), "", None


def _parse_nport_holdings(accession: str) -> dict | None:
    """Parse NPORT-P filing holdings using edgartools (sync, runs in thread).

    Returns dict with fund_name, total_assets, holdings_count, and holdings list,
    or None on failure.
    """
    try:
        filing = edgar_find(accession)
        if filing is None:
            return None
        report = filing.obj()
        if report is None:
            return None

        # Get fund metadata
        fund_name = None
        total_assets = None
        net_assets = None
        try:
            fund_name = report.general_info.series_name or report.general_info.name
        except (AttributeError, TypeError):
            pass
        try:
            total_assets = float(report.fund_info.total_assets) if report.fund_info.total_assets else None
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            net_assets = float(report.fund_info.net_assets) if report.fund_info.net_assets else None
        except (AttributeError, TypeError, ValueError):
            pass

        # Get securities (non-derivative holdings)
        df = report.securities_data()
        if df is None or df.empty:
            return {
                "fund_name": fund_name,
                "total_assets": total_assets,
                "net_assets": net_assets,
                "holdings_count": 0,
                "holdings": [],
            }

        # Convert DataFrame to compact list of dicts
        holdings = []
        for _, row in df.iterrows():
            holding: dict = {"name": row.get("name") or row.get("title")}
            if row.get("ticker"):
                holding["ticker"] = row["ticker"]
            if row.get("cusip"):
                holding["cusip"] = row["cusip"]
            val = row.get("value_usd")
            if val is not None:
                try:
                    holding["value_usd"] = float(val)
                except (TypeError, ValueError):
                    pass
            bal = row.get("balance")
            if bal is not None:
                try:
                    holding["shares"] = float(bal)
                except (TypeError, ValueError):
                    pass
            pct = row.get("pct_value")
            if pct is not None:
                try:
                    holding["pct"] = round(float(pct), 4)
                except (TypeError, ValueError):
                    pass
            cat = row.get("asset_category")
            if cat:
                holding["category"] = str(cat)
            country = row.get("investment_country")
            if country:
                holding["country"] = str(country)
            holdings.append(holding)

        # Sort by value descending
        holdings.sort(key=lambda h: h.get("value_usd") or 0, reverse=True)

        return {
            "fund_name": fund_name,
            "total_assets": total_assets,
            "net_assets": net_assets,
            "holdings_count": len(holdings),
            "holdings": holdings,
        }
    except Exception:
        logger.exception("Failed to parse NPORT-P filing %s", accession)
        return None


def _extract_filing_section(symbol: str, form: str, section_key: str, accession: str | None) -> str | None:
    """Extract a section from a filing using edgartools (sync, runs in thread).

    Returns plain text of the section, or None if not found.
    """
    try:
        if accession:
            filing = edgar_find(accession)
        else:
            company = Company(symbol)
            filings = company.get_filings(form=form)
            filing = filings.latest()

        if filing is None:
            return None

        typed_obj = filing.obj()
        if typed_obj is None:
            return None

        # Use __getitem__ which returns plain text
        text = typed_obj[section_key]
        return text
    except Exception:
        logger.exception("Failed to extract section %s from %s %s", section_key, symbol, form)
        return None


async def _llm_filter_sections(
    sections: dict[str, str],
    query: str,
    max_chars: int,
) -> dict[str, str]:
    """Use GPT-5-mini to filter section text to only relevant paragraphs.

    Sends each section to the LLM asking it to identify and extract only the
    paragraphs relevant to the query. Returns filtered text per section.
    """
    if not OPENAI_API_KEY:
        # No API key — return truncated full text as fallback
        return {k: v[:max_chars] for k, v in sections.items()}

    filtered: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=60) as http:
        for section_name, text in sections.items():
            if not text:
                continue

            # If text is already small enough, skip LLM call
            if len(text) <= max_chars:
                filtered[section_name] = text
                continue

            prompt = (
                f"You are a financial document analyst. Extract ONLY the paragraphs from the following "
                f"SEC filing section that are relevant to this query: \"{query}\"\n\n"
                f"Return the relevant paragraphs verbatim, separated by blank lines. "
                f"If nothing is relevant, respond with 'No relevant content found.'\n\n"
                f"--- SECTION: {section_name} ---\n{text}"
            )

            try:
                resp = await http.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_chars // 3,  # rough char-to-token ratio
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                filtered[section_name] = content[:max_chars]
            except Exception:
                logger.exception("LLM filtering failed for section %s", section_name)
                filtered[section_name] = text[:max_chars]

    return filtered


def register(mcp: FastMCP, client: AsyncFMPDataClient) -> None:
    del client  # unused — SEC EDGAR is a free public API

    @mcp.tool(
        annotations={
            "title": "SEC EDGAR Filing Search (NPORT-P fund holdings reverse lookup)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def sec_filings_search(
        query: str,
        forms: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        entity: str | None = None,
        traded_only: bool = False,
        parse_holdings: bool = True,
        limit: int = 50,
    ) -> dict:
        """Search SEC EDGAR filings by full-text content. Best for NPORT-P reverse lookups.

        PRIMARY USE CASE — NPORT-P reverse lookup (forms="NPORT-P"):
        Find which publicly-traded funds hold a private or public company.
        This is the only way to answer "who holds X?" for private companies
        like SpaceX, Anthropic, xAI, Stripe, etc. NPORT-P filings contain
        structured holdings data, so matches are high-signal (actual positions).
        When parse_holdings=True (default), automatically parses the actual
        portfolio holdings from each NPORT-P filing — returns fund names,
        position sizes, values, and portfolio weights instead of just filing links.
        Examples:
        - "which funds hold SpaceX?" → query="SpaceX", forms="NPORT-P"
        - "who has Anthropic exposure?" → query="Anthropic", forms="NPORT-P"
        - Publicly-traded funds only: add traded_only=True to filter to
          closed-end funds with tickers (DXYZ, ECAT, BSTZ, BST, etc.) that
          investors can actually buy on the stock market. Without this flag,
          results include mutual fund trusts (Fidelity, Vanguard) that are
          not directly tradeable as stocks.

        SECONDARY USE CASES:
        - Cross-filing research: query="SpaceX" (no form filter) searches all
          10-K, 8-K, S-1, Form D, etc. These are noisier — a mention could be
          a holding, customer, competitor, or passing reference.
        - Form D private offerings: query="AI", forms="D"

        Args:
            query: Search term (e.g. "SpaceX", "Anthropic"). Exact phrase match.
            forms: Comma-separated form types. Use "NPORT-P" for fund holdings
                reverse lookup (recommended default). Other options: "10-K",
                "8-K", "D", "S-1", or omit for all forms.
            start_date: Filter filings from this date (YYYY-MM-DD). Default: ~2 years back.
            end_date: Filter filings to this date (YYYY-MM-DD). Default: today.
            entity: Filter by filer entity name (e.g. "Fidelity").
            traded_only: If True, only return entities/filings with a stock ticker
                (publicly-traded closed-end funds like DXYZ, BSTZ). Filters out
                mutual fund trusts without tickers. Default: False.
            parse_holdings: If True and forms includes "NPORT-P", automatically
                parse the actual holdings from each filing using edgartools.
                Returns structured position data (name, value, shares, weight).
                Set to False for metadata-only results. Default: True.
            limit: Max results to return (1-100, default 50).
        """
        if not EDGAR_USER_AGENT:
            return {"error": "EDGAR_USER_AGENT env var is required (e.g. 'YourApp/1.0 (you@example.com)')"}

        query = query.strip()
        if not query:
            return {"error": "query is required"}

        limit = max(1, min(limit, 100))

        raw = await _edgar_search(query, forms, start_date, end_date, entity, limit)
        if raw is None:
            return {"error": "SEC EDGAR EFTS request failed"}

        # Total hits
        total_hits = 0
        hits_data = raw.get("hits", {})
        if isinstance(hits_data, dict):
            total_hits = hits_data.get("total", {}).get("value", 0)
            hit_list = hits_data.get("hits", [])
        else:
            hit_list = []

        # Parse aggregations for entity and form breakdowns
        aggregations = raw.get("aggregations", {})

        # Form breakdown
        form_breakdown: dict[str, int] = {}
        form_agg = aggregations.get("form_filter", {})
        for bucket in form_agg.get("buckets", []):
            form_breakdown[bucket.get("key", "unknown")] = bucket.get("doc_count", 0)

        # Entity breakdown
        entity_breakdown: list[dict] = []
        entity_agg = aggregations.get("entity_filter", {})
        for bucket in entity_agg.get("buckets", []):
            display = bucket.get("key", "")
            name, cik, ticker = _parse_entity(display)
            entry: dict = {
                "entity": name,
                "cik": cik,
                "count": bucket.get("doc_count", 0),
            }
            if ticker:
                entry["ticker"] = ticker
            entity_breakdown.append(entry)

        # Parse individual filings from hits
        filings: list[dict] = []
        for hit in hit_list:
            src = hit.get("_source", {})
            display_names = src.get("display_names") or []
            entity_display = display_names[0] if display_names else ""
            name, cik, ticker = _parse_entity(entity_display)

            # CIK may also come from the ciks array
            if not cik:
                ciks = src.get("ciks") or []
                cik = ciks[0] if ciks else ""

            accession = src.get("adsh", "")

            filing: dict = {
                "entity": name,
                "cik": cik,
                "form": src.get("form", ""),
                "filed": src.get("file_date", ""),
                "period": src.get("period_ending", ""),
                "accession": accession,
            }
            if ticker:
                filing["ticker"] = ticker
            if cik and accession:
                filing["url"] = _build_filing_url(cik, accession)
            filings.append(filing)

        # Filter to publicly-traded entities only (those with tickers)
        if traded_only:
            entity_breakdown = [e for e in entity_breakdown if e.get("ticker")]
            filings = [f for f in filings if f.get("ticker")]

        # Parse NPORT-P holdings if requested
        is_nport = forms and "NPORT" in forms.upper()
        if parse_holdings and is_nport:
            parse_count = min(len(filings), _MAX_PARSE_FILINGS)
            filings_to_parse = filings[:parse_count]

            # Parse in parallel using thread pool (edgartools is sync)
            parse_tasks = [
                asyncio.to_thread(_parse_nport_holdings, f["accession"])
                for f in filings_to_parse
                if f.get("accession")
            ]
            if parse_tasks:
                parsed_results = await asyncio.gather(*parse_tasks, return_exceptions=True)
                for i, parsed in enumerate(parsed_results):
                    if isinstance(parsed, dict) and i < len(filings_to_parse):
                        filings_to_parse[i]["fund_name"] = parsed.get("fund_name")
                        filings_to_parse[i]["total_assets"] = parsed.get("total_assets")
                        filings_to_parse[i]["net_assets"] = parsed.get("net_assets")
                        filings_to_parse[i]["holdings_count"] = parsed.get("holdings_count")
                        filings_to_parse[i]["holdings"] = parsed.get("holdings")

        result: dict = {
            "query": query,
            "total_hits": total_hits,
        }
        if forms:
            result["forms_filter"] = forms
        if entity:
            result["entity_filter"] = entity
        if traded_only:
            result["traded_only"] = True
        if form_breakdown:
            result["form_breakdown"] = form_breakdown
        if entity_breakdown:
            result["entity_breakdown"] = entity_breakdown
        result["showing"] = len(filings)
        result["filings"] = filings

        return result

    @mcp.tool(
        annotations={
            "title": "SEC Filing Section Extraction",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def filing_sections(
        symbol: str,
        form: str = "10-K",
        sections: list[str] | None = None,
        query: str | None = None,
        accession: str | None = None,
        max_chars: int = 15000,
    ) -> dict:
        """Extract specific sections from SEC filings (10-K, 10-Q) with optional LLM filtering.

        Uses edgartools to parse filing structure and extract named sections.
        When a query is provided and OPENAI_KEY is set, uses GPT-4.1-mini to
        filter each section down to only the paragraphs relevant to the query,
        dramatically reducing token usage.

        Without a query, returns the full section text truncated to max_chars.

        Examples:
        - AAPL risk factors: symbol="AAPL", sections=["risk_factors"]
        - TSLA AI-related risks: symbol="TSLA", sections=["risk_factors"], query="artificial intelligence"
        - Latest 10-Q MD&A: symbol="MSFT", form="10-Q", sections=["mda"]
        - Specific filing: accession="0000320193-24-000123", sections=["risk_factors", "mda"]

        Args:
            symbol: Stock ticker (e.g. "AAPL"). Used to find latest filing if accession not given.
            form: Filing type — "10-K" (default) or "10-Q".
            sections: Section names to extract. Options for 10-K: business, risk_factors,
                mda, financials, legal, properties, cybersecurity, executive_compensation.
                Options for 10-Q: financials, mda, market_risk, controls, legal, risk_factors.
                Default: ["risk_factors", "mda"] for 10-K, ["mda", "risk_factors"] for 10-Q.
            query: Optional natural language filter. When provided, uses GPT-4.1-mini to
                extract only the paragraphs relevant to this query from each section.
                E.g. "supply chain risks", "AI regulation", "China exposure".
            accession: Specific filing accession number. If omitted, uses the latest
                filing of the given form type for the symbol.
            max_chars: Maximum characters per section in the response (default 15000).
                Controls token budget. Set lower for concise results.
        """
        symbol = symbol.upper().strip()
        form = form.upper().strip()
        max_chars = max(1000, min(max_chars, 50000))

        # Validate form type
        if form not in ("10-K", "10-Q"):
            return {"error": f"Unsupported form type '{form}'. Use '10-K' or '10-Q'."}

        # Resolve section keys
        section_map = _TENK_SECTIONS if form == "10-K" else _TENQ_SECTIONS
        if sections is None:
            sections = ["risk_factors", "mda"]

        # Validate section names
        invalid = [s for s in sections if s not in section_map]
        if invalid:
            return {
                "error": f"Invalid section(s): {invalid}. Valid options: {list(section_map.keys())}",
            }

        # Extract each section in parallel (edgartools is sync, use thread pool)
        # Note: each call creates its own Company/Filing lookup, but edgartools
        # caches filing documents permanently so subsequent calls are fast.
        extract_tasks = [
            asyncio.to_thread(
                _extract_filing_section,
                symbol, form, section_map[s], accession,
            )
            for s in sections
        ]
        extracted = await asyncio.gather(*extract_tasks, return_exceptions=True)

        raw_sections: dict[str, str] = {}
        warnings: list[str] = []
        for i, result_or_err in enumerate(extracted):
            section_name = sections[i]
            if isinstance(result_or_err, Exception):
                warnings.append(f"{section_name}: extraction failed ({result_or_err})")
            elif result_or_err is None:
                warnings.append(f"{section_name}: not found in filing")
            else:
                raw_sections[section_name] = result_or_err

        if not raw_sections:
            return {
                "error": f"No sections could be extracted from {symbol} {form}",
                "_warnings": warnings,
            }

        # Apply LLM filtering if query provided, otherwise truncate
        if query and query.strip():
            output_sections = await _llm_filter_sections(raw_sections, query.strip(), max_chars)
            filter_method = "llm" if OPENAI_API_KEY else "truncated (no OPENAI_KEY)"
        else:
            output_sections = {k: v[:max_chars] for k, v in raw_sections.items()}
            filter_method = "truncated"

        result: dict = {
            "symbol": symbol,
            "form": form,
            "filter_method": filter_method,
        }
        if query:
            result["query"] = query
        if accession:
            result["accession"] = accession

        result["sections"] = {}
        for section_name, text in output_sections.items():
            result["sections"][section_name] = {
                "text": text,
                "chars": len(text),
                "original_chars": len(raw_sections.get(section_name, "")),
            }

        if warnings:
            result["_warnings"] = warnings

        return result
