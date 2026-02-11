"""Company overview and stock search tools."""

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
