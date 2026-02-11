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
        price_min: float | None = None,
        price_max: float | None = None,
        beta_min: float | None = None,
        beta_max: float | None = None,
        volume_min: int | None = None,
        dividend_yield_min: float | None = None,
        dividend_yield_max: float | None = None,
        country: str | None = None,
        is_etf: bool | None = None,
        is_actively_trading: bool | None = None,
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
            price_min: Minimum stock price
            price_max: Maximum stock price
            beta_min: Minimum beta (volatility vs market)
            beta_max: Maximum beta
            volume_min: Minimum daily volume
            dividend_yield_min: Minimum dividend yield (as percentage, e.g. 2.5)
            dividend_yield_max: Maximum dividend yield
            country: Filter by country code (e.g. "US", "CN")
            is_etf: Filter to ETFs only (true) or exclude ETFs (false)
            is_actively_trading: Filter to actively trading stocks only
            limit: Max results to return (default 20)
        """
        use_screener = any([
            exchange, sector, market_cap_min, market_cap_max,
            price_min, price_max, beta_min, beta_max, volume_min,
            dividend_yield_min, dividend_yield_max, country,
            is_etf is not None, is_actively_trading is not None,
        ])

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
            if price_min:
                params["priceMoreThan"] = price_min
            if price_max:
                params["priceLowerThan"] = price_max
            if beta_min:
                params["betaMoreThan"] = beta_min
            if beta_max:
                params["betaLowerThan"] = beta_max
            if volume_min:
                params["volumeMoreThan"] = volume_min
            if dividend_yield_min:
                params["dividendMoreThan"] = dividend_yield_min
            if dividend_yield_max:
                params["dividendLowerThan"] = dividend_yield_max
            if country:
                params["country"] = country
            if is_etf is not None:
                params["isEtf"] = str(is_etf).lower()
            if is_actively_trading is not None:
                params["isActivelyTrading"] = str(is_actively_trading).lower()

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
                "beta": item.get("beta"),
                "volume": item.get("volume"),
                "dividend_yield": item.get("lastAnnualDividend"),
                "country": item.get("country"),
                "is_etf": item.get("isEtf"),
                "is_actively_trading": item.get("isActivelyTrading"),
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
        """Get key executives with titles, compensation breakdown, and benchmarking.

        Returns CEO, CFO, and other C-suite executives with detailed compensation
        data and industry benchmarks.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        exec_data, comp_data, benchmark_data = await asyncio.gather(
            client.get_safe(
                "/stable/key-executives",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/executive-compensation",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/executive-compensation-benchmark",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        exec_list = exec_data if isinstance(exec_data, list) else []
        comp_list = comp_data if isinstance(comp_data, list) else []
        benchmark_list = benchmark_data if isinstance(benchmark_data, list) else []

        if not exec_list:
            return {"error": f"No executive data found for '{symbol}'"}

        # Build compensation lookup by name
        comp_by_name: dict[str, dict] = {}
        for comp in comp_list:
            name = comp.get("nameOfExecutive")
            if name:
                comp_by_name[name] = comp

        # Sort by total compensation descending (None/0 goes last)
        exec_list.sort(key=lambda e: e.get("pay") or 0, reverse=True)

        executives = []
        for e in exec_list:
            name = e.get("name")
            comp = comp_by_name.get(name, {})

            exec_entry = {
                "name": name,
                "title": e.get("title"),
                "pay": e.get("pay"),
                "currency": e.get("currencyPay"),
                "year_born": e.get("yearBorn"),
                "title_since": e.get("titleSince"),
                "gender": e.get("gender"),
            }

            # Add detailed compensation breakdown if available
            if comp:
                exec_entry["compensation_breakdown"] = {
                    "filing_date": comp.get("filingDate"),
                    "accepted_date": comp.get("acceptedDate"),
                    "year": comp.get("year"),
                    "salary": comp.get("salary"),
                    "bonus": comp.get("bonus"),
                    "stock_award": comp.get("stockAward"),
                    "incentive_plan_compensation": comp.get("incentivePlanCompensation"),
                    "all_other_compensation": comp.get("allOtherCompensation"),
                    "total": comp.get("total"),
                }

            executives.append(exec_entry)

        # Process benchmarks
        benchmarks = []
        for bench in benchmark_list:
            benchmarks.append({
                "industry": bench.get("industry"),
                "year": bench.get("year"),
                "salary_average": bench.get("averageSalary"),
                "bonus_average": bench.get("averageBonus"),
                "stock_award_average": bench.get("averageStockAward"),
                "incentive_plan_average": bench.get("averageIncentivePlanCompensation"),
                "total_average": bench.get("averageTotal"),
                "percentile_25": bench.get("percentile25"),
                "percentile_50": bench.get("percentile50"),
                "percentile_75": bench.get("percentile75"),
            })

        result = {
            "symbol": symbol,
            "count": len(executives),
            "executives": executives,
        }

        if benchmarks:
            result["industry_benchmarks"] = benchmarks

        # Flag partial data
        warnings = []
        if not comp_list:
            warnings.append("detailed compensation data unavailable")
        if not benchmark_list:
            warnings.append("industry benchmark data unavailable")
        if warnings:
            result["_warnings"] = warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Employee History",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def employee_history(symbol: str) -> dict:
        """Get employee count history with growth analysis.

        Returns current employee count, historical series, YoY changes,
        and 5Y/10Y CAGR.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        data = await client.get_safe(
            "/stable/employee-count",
            params={"symbol": symbol},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        history_list = data if isinstance(data, list) else []

        if not history_list:
            return {"error": f"No employee data found for '{symbol}'"}

        # Sort by period date descending (newest first)
        history_list.sort(key=lambda h: h.get("periodDate") or "", reverse=True)

        current_count = None
        if history_list:
            current_count = history_list[0].get("employeeCount")

        # Build historical series with YoY changes
        history = []
        for i, h in enumerate(history_list):
            count = h.get("employeeCount")
            entry = {
                "period_date": h.get("periodDate"),
                "filing_date": h.get("filingDate"),
                "employee_count": count,
                "source": h.get("source"),
                "form_type": h.get("formType"),
            }

            # Calculate YoY change if we have data from a year ago
            if i > 0 and count is not None:
                # Look for entry roughly 1 year back
                for prev in history_list[i:]:
                    prev_count = prev.get("employeeCount")
                    if prev_count and prev_count != count:
                        yoy_change = count - prev_count
                        yoy_pct = round((count / prev_count - 1) * 100, 2) if prev_count else None
                        entry["yoy_change"] = yoy_change
                        entry["yoy_change_pct"] = yoy_pct
                        break

            history.append(entry)

        # Calculate CAGR if we have enough history
        def calc_cagr(years: int) -> float | None:
            if len(history_list) < 2:
                return None
            start_count = None
            for h in reversed(history_list):
                if h.get("employeeCount"):
                    start_count = h.get("employeeCount")
                    break
            if not current_count or not start_count or start_count == 0:
                return None
            actual_years = len(history_list) - 1
            if actual_years < years:
                years = actual_years
            if years <= 0:
                return None
            return round((pow(current_count / start_count, 1 / years) - 1) * 100, 2)

        result = {
            "symbol": symbol,
            "current_employee_count": current_count,
            "count": len(history),
            "history": history,
        }

        # Add CAGR metrics if we have enough data
        cagr_5y = calc_cagr(5)
        cagr_10y = calc_cagr(10)
        if cagr_5y is not None or cagr_10y is not None:
            result["growth_metrics"] = {}
            if cagr_5y is not None:
                result["growth_metrics"]["cagr_5y_pct"] = cagr_5y
            if cagr_10y is not None:
                result["growth_metrics"]["cagr_10y_pct"] = cagr_10y

        return result

    @mcp.tool(
        annotations={
            "title": "Delisted Companies",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def delisted_companies(
        query: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Search for delisted companies.

        Returns companies that have been removed from exchange listings,
        with delisting date and reason.

        Args:
            query: Company name or ticker to search for (optional)
            limit: Max results to return (default 20)
        """
        params: dict = {}
        if query:
            params["query"] = query
        if limit:
            params["limit"] = limit

        data = await client.get_safe(
            "/stable/delisted-companies",
            params=params if params else None,
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        companies_list = data if isinstance(data, list) else []

        if not companies_list:
            msg = f"No delisted companies found"
            if query:
                msg += f" matching '{query}'"
            return {"error": msg}

        # Sort by delisted date descending (newest first)
        companies_list.sort(key=lambda c: c.get("delistedDate") or "", reverse=True)

        companies = []
        for c in companies_list[:limit]:
            companies.append({
                "symbol": c.get("symbol"),
                "company_name": c.get("companyName"),
                "exchange": c.get("exchange"),
                "delisted_date": c.get("delistedDate"),
                "ipo_date": c.get("ipoDate"),
            })

        return {
            "query": query,
            "count": len(companies),
            "companies": companies,
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
        form_type: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Get recent SEC filings for a company.

        Returns filing date, form type, and links. Optionally filter by form type.

        Common form types:
        - 10-K: Annual report
        - 10-Q: Quarterly report
        - 8-K: Current report (material events)
        - DEF 14A: Proxy statement
        - S-1: IPO registration
        - 13F: Institutional holdings report
        - 4: Insider trading report

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            form_type: Optional filing type filter (e.g. "10-K", "10-Q", "8-K")
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

        # Client-side form type filter
        if form_type:
            form_type_upper = form_type.upper().strip()
            filings_list = [f for f in filings_list if (f.get("formType") or "").upper() == form_type_upper]

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
            "form_type_filter": form_type,
            "count": len(filings),
            "filings": filings,
        }

    @mcp.tool(
        annotations={
            "title": "Symbol Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def symbol_lookup(
        query: str,
        type: str = "name",
    ) -> dict:
        """Look up stock symbols by name, CIK, or CUSIP.

        Converts between different company identifiers (symbol, CIK, CUSIP).

        Args:
            query: Search query (company name, CIK, or CUSIP)
            type: Lookup type - "name", "cik", or "cusip" (default "name")
        """
        type_lower = type.lower().strip()

        if type_lower == "cik":
            endpoint = "/stable/cik-search"
            param_key = "cik"
        elif type_lower == "cusip":
            endpoint = "/stable/cusip-search"
            param_key = "cusip"
        else:
            # Default to name search
            endpoint = "/stable/cik-search"
            param_key = "name"

        data = await client.get_safe(
            endpoint,
            params={param_key: query},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        results_list = data if isinstance(data, list) else []

        if not results_list:
            return {"error": f"No results found for {type} '{query}'"}

        results = []
        for item in results_list:
            results.append({
                "symbol": item.get("symbol"),
                "company_name": item.get("companyName") or item.get("name"),
                "cik": item.get("cik"),
                "cusip": item.get("cusip"),
                "exchange": item.get("exchange") or item.get("exchangeShortName"),
            })

        return {
            "query": query,
            "lookup_type": type_lower,
            "count": len(results),
            "results": results,
        }
