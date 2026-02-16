"""SEC EDGAR full-text search via EFTS (Electronic Full-Text Search) API."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_data import AsyncFMPDataClient

EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_USER_AGENT = "PantainosFMP/1.0 (research@pantainos.com)"
EDGAR_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


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
    """Parse EFTS entity display name into (name, cik, ticker).

    Examples:
        "Destiny Tech100 Inc.  (DXYZ)  (CIK 0001843974)" -> ("Destiny Tech100 Inc.", "0001843974", "DXYZ")
        "Blackstone Alternative Investment Funds  (CIK 0001557794)" -> ("Blackstone Alternative Investment Funds", "0001557794", None)
    """
    m = _ENTITY_PATTERN.match(display_name.strip())
    if m:
        return m.group(1).strip(), m.group(3).zfill(10), m.group(2)
    return display_name.strip(), "", None


def register(mcp: FastMCP, client: AsyncFMPDataClient) -> None:
    del client  # unused — SEC EDGAR is a free public API

    @mcp.tool(
        annotations={
            "title": "SEC Filings Search",
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
        limit: int = 50,
    ) -> dict:
        """Search SEC EDGAR filings by full-text content.

        Searches the text of all SEC filings (10-K, 8-K, NPORT-P, Form D, S-1, etc.)
        using SEC's EFTS full-text search. Especially powerful for reverse lookups:
        - "which funds hold SpaceX?" → forms="NPORT-P"
        - "who mentions Anthropic in SEC filings?" → no form filter
        - "Form D filings mentioning AI" → forms="D"

        NPORT-P results are high-signal (structured holdings data). Other form types
        (10-K, 8-K, S-1) are noisier — mentions could be holdings, customers,
        competitors, or passing references.

        Args:
            query: Search term (e.g. "SpaceX", "Anthropic"). Exact phrase match.
            forms: Comma-separated form types to filter (e.g. "NPORT-P", "10-K,8-K"). Default: all forms.
            start_date: Filter filings from this date (YYYY-MM-DD). Default: ~2 years back.
            end_date: Filter filings to this date (YYYY-MM-DD). Default: today.
            entity: Filter by filer entity name (e.g. "Fidelity").
            limit: Max results to return (1-100, default 50).
        """
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

        result: dict = {
            "query": query,
            "total_hits": total_hits,
        }
        if forms:
            result["forms_filter"] = forms
        if entity:
            result["entity_filter"] = entity
        if form_breakdown:
            result["form_breakdown"] = form_breakdown
        if entity_breakdown:
            result["entity_breakdown"] = entity_breakdown
        result["showing"] = len(filings)
        result["filings"] = filings

        return result
