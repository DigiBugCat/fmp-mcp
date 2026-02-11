"""Company overview, search, executives, and SEC filings tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def _safe_first(data: list | None) -> dict:
    """Return first element of list or empty dict."""
    if isinstance(data, list) and data:
        return data[0]
    return {}


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Company Overview",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def company_overview(symbol: str) -> dict:
        """Get a comprehensive company snapshot including profile, valuation ratios, and current quote.

        Use this FIRST for any stock analysis query. Returns name, sector,
        market cap, P/E, P/B, dividend yield, ROE, debt/equity, and more.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL", "MSFT")
        """
        symbol = symbol.upper().strip()
        sym_params = {"symbol": symbol}

        profile_data, quote_data, ratios_data = await asyncio.gather(
            client.get_safe(
                "/stable/profile",
                params=sym_params,
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/quote",
                params=sym_params,
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/ratios-ttm",
                params=sym_params,
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
        )

        profile = _safe_first(profile_data)
        quote = _safe_first(quote_data)
        ratios = _safe_first(ratios_data)

        if not profile and not quote:
            return {"error": f"No data found for symbol '{symbol}'"}

        result = {
            "symbol": symbol,
            "name": profile.get("companyName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "ceo": profile.get("ceo"),
            "employees": profile.get("fullTimeEmployees"),
            "description": profile.get("description"),
            "exchange": profile.get("exchange"),
            "country": profile.get("country"),
            "website": profile.get("website"),
            # Current quote
            "price": quote.get("price"),
            "market_cap": quote.get("marketCap"),
            "volume": quote.get("volume"),
            "change_pct": quote.get("changePercentage"),
            "day_range": {
                "low": quote.get("dayLow"),
                "high": quote.get("dayHigh"),
            },
            "year_range": {
                "low": quote.get("yearLow"),
                "high": quote.get("yearHigh"),
            },
            "sma_50": quote.get("priceAvg50"),
            "sma_200": quote.get("priceAvg200"),
            # Valuation ratios (TTM)
            "ratios": {
                "pe_ttm": ratios.get("priceToEarningsRatioTTM"),
                "pb_ttm": ratios.get("priceToBookRatioTTM"),
                "ps_ttm": ratios.get("priceToSalesRatioTTM"),
                "peg_ttm": ratios.get("priceToEarningsGrowthRatioTTM"),
                "ev_ebitda_ttm": ratios.get("enterpriseValueMultipleTTM"),
                "dividend_yield_ttm": ratios.get("dividendYieldTTM"),
                "roe_ttm": ratios.get("returnOnEquityTTM"),
                "roa_ttm": ratios.get("returnOnAssetsTTM"),
                "debt_equity_ttm": ratios.get("debtToEquityRatioTTM"),
                "current_ratio_ttm": ratios.get("currentRatioTTM"),
                "gross_margin_ttm": ratios.get("grossProfitMarginTTM"),
                "operating_margin_ttm": ratios.get("operatingProfitMarginTTM"),
                "net_margin_ttm": ratios.get("netProfitMarginTTM"),
                "price_to_fcf_ttm": ratios.get("priceToFreeCashFlowRatioTTM"),
            },
        }

        # Flag partial data
        errors = []
        if not profile:
            errors.append("profile data unavailable")
        if not quote:
            errors.append("quote data unavailable")
        if not ratios:
            errors.append("ratio data unavailable")
        if errors:
            result["_warnings"] = errors

        return result

    @mcp.tool(
        annotations={
            "title": "Stock Search",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def stock_search(
        query: str,
        exchange: str | None = None,
        sector: str | None = None,
        market_cap_min: int | None = None,
        market_cap_max: int | None = None,
        limit: int = 20,
    ) -> dict:
        """Find stocks by name/ticker or screen by criteria.

        For simple name/ticker lookup, just pass query. For filtered screening,
        use the optional parameters.

        Args:
            query: Company name or ticker to search for
            exchange: Filter by exchange (e.g. "NYSE", "NASDAQ")
            sector: Filter by sector (e.g. "Technology", "Healthcare")
            market_cap_min: Minimum market cap in dollars
            market_cap_max: Maximum market cap in dollars
            limit: Max results to return (default 20)
        """
        use_screener = any([exchange, sector, market_cap_min, market_cap_max])

        if use_screener:
            params: dict = {"limit": limit}
            if exchange:
                params["exchangeShortName"] = exchange
            if sector:
                params["sector"] = sector
            if market_cap_min:
                params["marketCapMoreThan"] = market_cap_min
            if market_cap_max:
                params["marketCapLowerThan"] = market_cap_max

            data = await client.get(
                "/stable/company-screener",
                params=params,
                cache_ttl=client.TTL_HOURLY,
            )
        else:
            data = await client.get(
                "/stable/search-name",
                params={"query": query, "limit": limit},
                cache_ttl=client.TTL_HOURLY,
            )

        if not isinstance(data, list):
            return {"results": [], "count": 0}

        results = []
        for item in data[:limit]:
            results.append({
                "symbol": item.get("symbol"),
                "name": item.get("companyName") or item.get("name"),
                "exchange": item.get("exchangeShortName") or item.get("exchange"),
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "market_cap": item.get("marketCap"),
                "price": item.get("price"),
            })

        return {"results": results, "count": len(results)}

    @mcp.tool(
        annotations={
            "title": "Company Executives",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def company_executives(symbol: str) -> dict:
        """Get key executives with titles and compensation.

        Returns CEO, CFO, and other C-suite executives sorted by compensation.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        data = await client.get_safe(
            "/stable/key-executives",
            params={"symbol": symbol},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        exec_list = data if isinstance(data, list) else []

        if not exec_list:
            return {"error": f"No executive data found for '{symbol}'"}

        # Sort by compensation descending (None/0 goes last)
        exec_list.sort(key=lambda e: e.get("pay") or 0, reverse=True)

        executives = []
        for e in exec_list:
            executives.append({
                "name": e.get("name"),
                "title": e.get("title"),
                "pay": e.get("pay"),
                "currency": e.get("currencyPay"),
                "year_born": e.get("yearBorn"),
                "title_since": e.get("titleSince"),
                "gender": e.get("gender"),
            })

        return {
            "symbol": symbol,
            "count": len(executives),
            "executives": executives,
        }

    @mcp.tool(
        annotations={
            "title": "SEC Filings",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def sec_filings(
        symbol: str,
        type: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Get recent SEC filings for a company.

        Returns filing date, form type, and links. Optionally filter by type
        (e.g. "10-K", "10-Q", "8-K").

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            type: Optional filing type filter (e.g. "10-K", "10-Q", "8-K")
            limit: Max filings to return (default 20)
        """
        symbol = symbol.upper().strip()
        limit = max(1, min(limit, 100))

        # Fetch profile for CIK (needed for filings lookup)
        profile_data = await client.get_safe(
            "/stable/profile",
            params={"symbol": symbol},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )
        profile = _safe_first(profile_data)
        cik = profile.get("cik")

        if not cik:
            return {"error": f"Could not find CIK for '{symbol}'"}

        data = await client.get_safe(
            "/stable/sec-filings-search/cik",
            params={"cik": cik, "limit": limit},
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        filings_list = data if isinstance(data, list) else []

        if not filings_list:
            return {"error": f"No SEC filings found for '{symbol}' (CIK: {cik})"}

        # Client-side type filter
        if type:
            type_upper = type.upper().strip()
            filings_list = [f for f in filings_list if (f.get("formType") or "").upper() == type_upper]

        # Sort by filing date descending
        filings_list.sort(key=lambda f: f.get("filingDate") or "", reverse=True)

        filings = []
        for f in filings_list[:limit]:
            filings.append({
                "filing_date": f.get("filingDate"),
                "accepted_date": f.get("acceptedDate"),
                "form_type": f.get("formType"),
                "url": f.get("finalLink") or f.get("link"),
                "cik": f.get("cik"),
            })

        return {
            "symbol": symbol,
            "cik": cik,
            "type_filter": type,
            "count": len(filings),
            "filings": filings,
        }
