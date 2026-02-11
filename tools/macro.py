"""Macro-economic data tools: treasury rates, economic calendar, market overview, IPOs, dividends calendar, indices, sector valuation."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fmp_client import FMPClient
    from fastmcp import FastMCP

MIN_MARKET_CAP = 1_000_000_000  # $1B floor for movers


def _safe_first(data: list | None) -> dict:
    if isinstance(data, list) and data:
        return data[0]
    return {}


async def _fetch_sectors(client: "FMPClient") -> list[dict]:
    """Fetch sector performance from NYSE + NASDAQ and average by sector.

    /stable/sector-performance-snapshot requires `date` and returns
    per-exchange data with `averageChange` (not `changesPercentage`).
    """
    today_str = date.today().isoformat()
    nyse_data, nasdaq_data = await asyncio.gather(
        client.get_safe(
            "/stable/sector-performance-snapshot",
            params={"date": today_str, "exchange": "NYSE"},
            cache_ttl=client.TTL_REALTIME,
            default=[],
        ),
        client.get_safe(
            "/stable/sector-performance-snapshot",
            params={"date": today_str, "exchange": "NASDAQ"},
            cache_ttl=client.TTL_REALTIME,
            default=[],
        ),
    )

    nyse_list = nyse_data if isinstance(nyse_data, list) else []
    nasdaq_list = nasdaq_data if isinstance(nasdaq_data, list) else []

    # Build lookup by sector and average
    sector_vals: dict[str, list[float]] = {}
    for entry in nyse_list + nasdaq_list:
        sector = entry.get("sector")
        change = entry.get("averageChange")
        if sector and change is not None:
            sector_vals.setdefault(sector, []).append(change)

    sectors = []
    for sector, vals in sector_vals.items():
        avg = round(sum(vals) / len(vals), 4)
        sectors.append({"sector": sector, "change_pct": avg})

    sectors.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    return sectors


async def _fetch_movers_with_mcap(client: "FMPClient") -> tuple[list, list, list]:
    """Fetch gainers/losers/actives and filter by market cap using batch-quote.

    Returns (gainers, losers, actives) lists with marketCap-enriched entries,
    filtered to MIN_MARKET_CAP.
    """
    gainers_data, losers_data, actives_data = await asyncio.gather(
        client.get_safe("/stable/biggest-gainers", cache_ttl=client.TTL_REALTIME, default=[]),
        client.get_safe("/stable/biggest-losers", cache_ttl=client.TTL_REALTIME, default=[]),
        client.get_safe("/stable/most-actives", cache_ttl=client.TTL_REALTIME, default=[]),
    )

    gainers_raw = gainers_data if isinstance(gainers_data, list) else []
    losers_raw = losers_data if isinstance(losers_data, list) else []
    actives_raw = actives_data if isinstance(actives_data, list) else []

    # Collect all unique symbols for batch quote
    all_symbols = set()
    for item in gainers_raw + losers_raw + actives_raw:
        sym = item.get("symbol")
        if sym:
            all_symbols.add(sym)

    # Batch-quote to get market caps (max ~150 symbols per call is fine)
    mcap_map: dict[str, float] = {}
    if all_symbols:
        symbols_str = ",".join(sorted(all_symbols))
        batch_data = await client.get_safe(
            "/stable/batch-quote",
            params={"symbols": symbols_str},
            cache_ttl=client.TTL_REALTIME,
            default=[],
        )
        batch_list = batch_data if isinstance(batch_data, list) else []
        for q in batch_list:
            sym = q.get("symbol")
            mc = q.get("marketCap")
            if sym and mc:
                mcap_map[sym] = mc

    def _enrich_and_filter(items: list[dict]) -> list[dict]:
        result = []
        for m in items:
            sym = m.get("symbol")
            mc = mcap_map.get(sym)
            if mc is not None and mc < MIN_MARKET_CAP:
                continue
            entry = {
                "symbol": sym,
                "name": m.get("name"),
                "price": m.get("price"),
                "change_pct": m.get("changesPercentage"),
            }
            if mc is not None:
                entry["market_cap"] = mc
            result.append(entry)
        return result

    return (
        _enrich_and_filter(gainers_raw),
        _enrich_and_filter(losers_raw),
        _enrich_and_filter(actives_raw),
    )


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Treasury Rates",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def treasury_rates() -> dict:
        """Get current US Treasury yield curve and equity risk premium.

        Returns latest yields across maturities, yield curve slope (10Y-2Y),
        inversion flag, and DCF-ready inputs (10Y rate + equity risk premium).
        """
        rates_data, erp_data = await asyncio.gather(
            client.get_safe(
                "/stable/treasury-rates",
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                "/stable/market-risk-premium",
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        rates_list = rates_data if isinstance(rates_data, list) else []
        latest = _safe_first(rates_list)

        if not latest:
            return {"error": "No treasury rate data available"}

        # Extract key maturities
        yields = {
            "1m": latest.get("month1"),
            "3m": latest.get("month3"),
            "6m": latest.get("month6"),
            "1y": latest.get("year1"),
            "2y": latest.get("year2"),
            "5y": latest.get("year5"),
            "10y": latest.get("year10"),
            "20y": latest.get("year20"),
            "30y": latest.get("year30"),
        }

        # Yield curve slope
        y10 = latest.get("year10")
        y2 = latest.get("year2")
        slope = None
        inverted = False
        if y10 is not None and y2 is not None:
            slope = round(y10 - y2, 3)
            inverted = slope < 0

        # DCF inputs from US market risk premium
        erp_list = erp_data if isinstance(erp_data, list) else []
        us_erp = None
        for entry in erp_list:
            if entry.get("country") == "United States":
                us_erp = entry.get("totalEquityRiskPremium")
                break

        dcf_inputs = {
            "risk_free_rate": y10,
            "equity_risk_premium": us_erp,
        }
        if y10 is not None and us_erp is not None:
            dcf_inputs["implied_cost_of_equity"] = round(y10 + us_erp, 3)

        result = {
            "date": latest.get("date"),
            "yields": yields,
            "curve_slope_10y_2y": slope,
            "curve_inverted": inverted,
            "dcf_inputs": dcf_inputs,
        }

        _warnings = []
        if not erp_list:
            _warnings.append("equity risk premium unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Economic Calendar",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def economic_calendar(days_ahead: int = 14) -> dict:
        """Get upcoming high-impact macro-economic events.

        Filters for important events (Fed, CPI, NFP, GDP, etc.) and
        sorts by date. Covers the next N days (default 14).

        Args:
            days_ahead: Number of days to look ahead (default 14, max 90)
        """
        days_ahead = min(max(days_ahead, 1), 90)
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        data = await client.get_safe(
            "/stable/economic-calendar",
            params={
                "from": today.isoformat(),
                "to": end_date.isoformat(),
            },
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        events_list = data if isinstance(data, list) else []

        if not events_list:
            return {"events": [], "count": 0, "period": f"{today.isoformat()} to {end_date.isoformat()}"}

        # Filter for high-impact events
        high_impact_keywords = [
            "fed", "fomc", "interest rate", "federal funds",
            "cpi", "consumer price", "inflation",
            "nonfarm", "non-farm", "employment", "unemployment", "jobless",
            "gdp", "gross domestic",
            "pce", "personal consumption",
            "retail sales",
            "ism", "pmi", "manufacturing",
            "housing starts", "building permits",
            "consumer confidence", "consumer sentiment",
            "trade balance",
            "treasury",
        ]

        filtered = []
        for event in events_list:
            event_name = (event.get("event") or "").lower()
            country = (event.get("country") or "").upper()

            # Only US events
            if country != "US":
                continue

            is_high_impact = any(kw in event_name for kw in high_impact_keywords)
            if not is_high_impact:
                continue

            filtered.append({
                "date": event.get("date"),
                "event": event.get("event"),
                "estimate": event.get("estimate"),
                "actual": event.get("actual"),
                "previous": event.get("previous"),
                "change": event.get("change"),
                "impact": event.get("impact"),
            })

        # Sort by date ascending
        filtered.sort(key=lambda x: x.get("date") or "")

        return {
            "events": filtered,
            "count": len(filtered),
            "period": f"{today.isoformat()} to {end_date.isoformat()}",
            "total_unfiltered": len(events_list),
        }

    @mcp.tool(
        annotations={
            "title": "Market Overview",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def market_overview() -> dict:
        """Get today's market snapshot: sector performance, biggest movers, and most active stocks.

        Returns sector rankings, top 5 gainers/losers, and most actively traded names.
        Movers are filtered to companies with market cap > $1B to exclude micro-caps.
        """
        sectors, (gainers, losers, actives) = await asyncio.gather(
            _fetch_sectors(client),
            _fetch_movers_with_mcap(client),
        )

        if not any([sectors, gainers, losers, actives]):
            return {"error": "No market data available"}

        result = {
            "sectors": sectors,
            "top_gainers": gainers[:5],
            "top_losers": losers[:5],
            "most_active": actives[:5],
        }

        _warnings = []
        if not sectors:
            _warnings.append("sector performance unavailable")
        if not gainers:
            _warnings.append("gainers data unavailable")
        if not losers:
            _warnings.append("losers data unavailable")
        if not actives:
            _warnings.append("most active data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "IPO Calendar",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def ipo_calendar(days_ahead: int = 14) -> dict:
        """Get upcoming IPOs within a date window.

        Returns company, expected date, price range, shares offered, exchange,
        and links to prospectus/disclosure documents.

        Args:
            days_ahead: Number of days to look ahead (default 14, max 90)
        """
        days_ahead = min(max(days_ahead, 1), 90)
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        # Fetch IPO calendar, prospectus, and disclosures in parallel
        calendar_data, prospectus_data, disclosure_data = await asyncio.gather(
            client.get_safe(
                "/stable/ipos-calendar",
                params={
                    "from": today.isoformat(),
                    "to": end_date.isoformat(),
                },
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                "/stable/ipos-prospectus",
                params={
                    "from": today.isoformat(),
                    "to": end_date.isoformat(),
                },
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                "/stable/ipos-disclosure",
                params={
                    "from": today.isoformat(),
                    "to": end_date.isoformat(),
                },
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
        )

        ipo_list = calendar_data if isinstance(calendar_data, list) else []
        prospectus_list = prospectus_data if isinstance(prospectus_data, list) else []
        disclosure_list = disclosure_data if isinstance(disclosure_data, list) else []

        if not ipo_list:
            return {
                "ipos": [],
                "count": 0,
                "period": f"{today.isoformat()} to {end_date.isoformat()}",
            }

        # Build prospectus and disclosure maps by symbol
        prospectus_map: dict[str, list] = {}
        for p in prospectus_list:
            symbol = p.get("symbol")
            if symbol:
                prospectus_map.setdefault(symbol, []).append({
                    "url": p.get("url"),
                    "title": p.get("title"),
                    "date": p.get("date"),
                })

        disclosure_map: dict[str, list] = {}
        for d in disclosure_list:
            symbol = d.get("symbol")
            if symbol:
                disclosure_map.setdefault(symbol, []).append({
                    "url": d.get("url"),
                    "title": d.get("title"),
                    "date": d.get("date"),
                })

        # Sort by date ascending
        ipo_list.sort(key=lambda x: x.get("date") or "")

        ipos = []
        for ipo in ipo_list:
            symbol = ipo.get("symbol")
            entry = {
                "symbol": symbol,
                "company": ipo.get("company"),
                "date": ipo.get("date"),
                "exchange": ipo.get("exchange"),
                "price_range": ipo.get("priceRange"),
                "shares": ipo.get("shares"),
                "market_cap": ipo.get("marketCap"),
                "actions": ipo.get("actions"),
            }

            # Add prospectus links if available
            if symbol in prospectus_map:
                entry["prospectus"] = prospectus_map[symbol]

            # Add disclosure links if available
            if symbol in disclosure_map:
                entry["disclosures"] = disclosure_map[symbol]

            ipos.append(entry)

        result = {
            "ipos": ipos,
            "count": len(ipos),
            "period": f"{today.isoformat()} to {end_date.isoformat()}",
        }

        _warnings = []
        if not prospectus_list:
            _warnings.append("prospectus data unavailable")
        if not disclosure_list:
            _warnings.append("disclosure data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Dividends Calendar",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def dividends_calendar(days_ahead: int = 14) -> dict:
        """Get upcoming ex-dividend dates across all stocks.

        Returns symbols going ex-dividend within the specified window.

        Args:
            days_ahead: Number of days to look ahead (default 14, max 90)
        """
        days_ahead = min(max(days_ahead, 1), 90)
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        data = await client.get_safe(
            "/stable/dividends-calendar",
            params={
                "from": today.isoformat(),
                "to": end_date.isoformat(),
            },
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        div_list = data if isinstance(data, list) else []

        if not div_list:
            return {
                "dividends": [],
                "count": 0,
                "period": f"{today.isoformat()} to {end_date.isoformat()}",
            }

        # Sort by date ascending
        div_list.sort(key=lambda x: x.get("date") or "")

        dividends = []
        for d in div_list:
            dividends.append({
                "symbol": d.get("symbol"),
                "ex_date": d.get("date"),
                "dividend": d.get("dividend"),
                "adj_dividend": d.get("adjDividend"),
                "record_date": d.get("recordDate"),
                "payment_date": d.get("paymentDate"),
                "yield_pct": d.get("yield"),
                "frequency": d.get("frequency"),
            })

        return {
            "dividends": dividends,
            "count": len(dividends),
            "period": f"{today.isoformat()} to {end_date.isoformat()}",
        }

    INDEX_ROUTES = {
        "sp500": "/stable/sp500-constituent",
        "nasdaq": "/stable/nasdaq-constituent",
        "dowjones": "/stable/dowjones-constituent",
    }

    @mcp.tool(
        annotations={
            "title": "Index Constituents",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def index_constituents(index: str) -> dict:
        """Get constituent list for a major market index.

        Returns all symbols in the index with sector classification.

        Args:
            index: Index name - "sp500", "nasdaq", or "dowjones"
        """
        index = index.lower().strip()
        if index not in INDEX_ROUTES:
            return {"error": f"Invalid index '{index}'. Use: {', '.join(INDEX_ROUTES.keys())}"}

        data = await client.get_safe(
            INDEX_ROUTES[index],
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        constituents_list = data if isinstance(data, list) else []

        if not constituents_list:
            return {"error": f"No constituent data found for '{index}'"}

        # Sort alphabetically by symbol
        constituents_list.sort(key=lambda x: x.get("symbol") or "")

        constituents = []
        for c in constituents_list:
            constituents.append({
                "symbol": c.get("symbol"),
                "name": c.get("name"),
                "sector": c.get("sector"),
                "sub_sector": c.get("subSector"),
                "head_quarter": c.get("headQuarter"),
                "date_first_added": c.get("dateFirstAdded"),
                "founded": c.get("founded"),
            })

        # Sector breakdown
        sector_counts: dict[str, int] = {}
        for c in constituents:
            sector = c.get("sector") or "Unknown"
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        return {
            "index": index,
            "count": len(constituents),
            "constituents": constituents,
            "sector_breakdown": dict(sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)),
        }

    @mcp.tool(
        annotations={
            "title": "Index Performance",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def index_performance(
        indices: list[str] | None = None,
    ) -> dict:
        """Get current prices and performance for major market indices.

        Returns per-index current price, change, and performance across
        multiple timeframes (1d, 1w, 1m, 3m, ytd, 1y).

        Args:
            indices: List of index symbols (default: ["^GSPC", "^DJI", "^IXIC", "^RUT"])
        """
        if indices is None:
            indices = ["^GSPC", "^DJI", "^IXIC", "^RUT"]

        # Clean up symbols
        indices = [idx.upper().strip() for idx in indices]

        # Get current quotes
        symbols_str = ",".join(indices)
        quote_data = await client.get_safe(
            "/stable/batch-quote",
            params={"symbols": symbols_str},
            cache_ttl=client.TTL_REALTIME,
            default=[],
        )

        quotes = quote_data if isinstance(quote_data, list) else []

        if not quotes:
            return {"error": f"No quote data found for indices: {', '.join(indices)}"}

        # Get historical data for each index
        today = date.today()
        one_year_ago = today - timedelta(days=365)

        # Fetch historical data for all indices
        historical_tasks = []
        for idx in indices:
            historical_tasks.append(
                client.get_safe(
                    "/stable/historical-price-eod/full",
                    params={
                        "symbol": idx,
                        "from": one_year_ago.isoformat(),
                        "to": today.isoformat(),
                    },
                    cache_ttl=client.TTL_12H,
                    default=[],
                )
            )

        historical_results = await asyncio.gather(*historical_tasks)

        # Build quote map
        quote_map = {q.get("symbol"): q for q in quotes}

        # Calculate performance for each index
        index_data = []
        for i, idx in enumerate(indices):
            quote = quote_map.get(idx, {})
            historical = historical_results[i] if i < len(historical_results) else []
            historical = historical if isinstance(historical, list) else []

            current_price = quote.get("price")
            day_change = quote.get("changesPercentage")

            # Calculate performance across timeframes
            from tools.market import _calc_performance
            performance = {}
            if current_price and historical:
                for period, days in [("1w", 5), ("1m", 21), ("3m", 63), ("ytd", None), ("1y", 252)]:
                    if days is None:
                        # YTD calculation
                        ytd_start = date(today.year, 1, 1)
                        ytd_history = [h for h in historical if h.get("date", "") >= ytd_start.isoformat()]
                        if ytd_history:
                            ytd_start_price = ytd_history[-1].get("close")
                            if ytd_start_price and ytd_start_price > 0:
                                performance["ytd"] = round((current_price / ytd_start_price - 1) * 100, 2)
                    else:
                        perf = _calc_performance(current_price, historical, days)
                        if perf is not None:
                            performance[period] = perf

            index_data.append({
                "symbol": idx,
                "name": quote.get("name"),
                "price": current_price,
                "change_pct": day_change,
                "performance": performance,
            })

        return {
            "indices": index_data,
            "count": len(index_data),
        }

    @mcp.tool(
        annotations={
            "title": "Market Hours",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def market_hours(
        exchange: str = "NYSE",
    ) -> dict:
        """Get current market status and trading hours.

        Returns market open/close status, regular trading hours,
        extended hours, and upcoming holidays.

        Args:
            exchange: Exchange name (default "NYSE")
        """
        exchange = exchange.upper().strip()

        # Use /stable/exchange-market-hours with exchange param
        hours_data = await client.get_safe(
            "/stable/exchange-market-hours",
            params={"exchange": exchange},
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        hours_list = hours_data if isinstance(hours_data, list) else []
        exchange_hours = _safe_first(hours_list)

        # Get upcoming holidays
        today = date.today()

        holidays_data = await client.get_safe(
            "/stable/holidays-by-exchange",
            params={"exchange": exchange},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        holidays_list = holidays_data if isinstance(holidays_data, list) else []

        # Filter to future dates and sort ascending
        upcoming_holidays = []
        today_str = today.isoformat()
        for h in holidays_list:
            h_date = h.get("date") or ""
            if h_date >= today_str:
                upcoming_holidays.append({
                    "date": h_date,
                    "name": h.get("name"),
                    "is_closed": h.get("isClosed"),
                })
        upcoming_holidays.sort(key=lambda h: h.get("date") or "")
        upcoming_holidays = upcoming_holidays[:5]

        result = {
            "exchange": exchange,
        }

        if exchange_hours:
            result["is_open"] = exchange_hours.get("isMarketOpen") or exchange_hours.get("isTheStockMarketOpen")
            result["name"] = exchange_hours.get("name")
            result["timezone"] = exchange_hours.get("timezone")
            result["regular_hours"] = {
                "open": exchange_hours.get("openingHour"),
                "close": exchange_hours.get("closingHour"),
            }

        result["upcoming_holidays"] = upcoming_holidays

        _warnings = []
        if not exchange_hours:
            _warnings.append(f"market hours data unavailable for {exchange}")
        if not upcoming_holidays:
            _warnings.append("holiday calendar unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Industry Performance",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def industry_performance(
        sector: str | None = None,
    ) -> dict:
        """Get industry performance rankings with valuation context.

        Returns industries ranked by performance with median P/E ratios.
        Optionally filter to a specific sector.

        Args:
            sector: Optional sector to filter by (e.g. "Technology")
        """
        today_str = date.today().isoformat()

        # Fetch industry performance from NYSE + NASDAQ
        nyse_perf, nasdaq_perf, nyse_pe, nasdaq_pe = await asyncio.gather(
            client.get_safe(
                "/stable/industry-performance-snapshot",
                params={"date": today_str, "exchange": "NYSE"},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/industry-performance-snapshot",
                params={"date": today_str, "exchange": "NASDAQ"},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/industry-pe-snapshot",
                params={"date": today_str, "exchange": "NYSE"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/industry-pe-snapshot",
                params={"date": today_str, "exchange": "NASDAQ"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        nyse_perf_list = nyse_perf if isinstance(nyse_perf, list) else []
        nasdaq_perf_list = nasdaq_perf if isinstance(nasdaq_perf, list) else []
        nyse_pe_list = nyse_pe if isinstance(nyse_pe, list) else []
        nasdaq_pe_list = nasdaq_pe if isinstance(nasdaq_pe, list) else []

        # Build performance map (average across exchanges)
        perf_map: dict[str, list[float]] = {}
        sector_map: dict[str, str] = {}

        for entry in nyse_perf_list + nasdaq_perf_list:
            industry = entry.get("industry")
            change = entry.get("averageChange")
            industry_sector = entry.get("sector")
            if industry and change is not None:
                perf_map.setdefault(industry, []).append(change)
                if industry_sector:
                    sector_map[industry] = industry_sector

        # Build PE map
        pe_map: dict[str, list[float]] = {}
        for entry in nyse_pe_list + nasdaq_pe_list:
            industry = entry.get("industry")
            pe = entry.get("pe")
            if industry and pe is not None and pe > 0:
                pe_map.setdefault(industry, []).append(pe)

        # Combine into industry data
        industries = []
        for industry, changes in perf_map.items():
            avg_change = round(sum(changes) / len(changes), 4)
            industry_sector = sector_map.get(industry)

            # Filter by sector if specified
            if sector and industry_sector and industry_sector.lower() != sector.lower():
                continue

            avg_pe = None
            if industry in pe_map:
                avg_pe = round(sum(pe_map[industry]) / len(pe_map[industry]), 2)

            industries.append({
                "industry": industry,
                "sector": industry_sector,
                "change_pct": avg_change,
                "median_pe": avg_pe,
            })

        if not industries:
            msg = "No industry performance data available"
            if sector:
                msg += f" for sector '{sector}'"
            return {"error": msg}

        # Sort by performance descending
        industries.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)

        result = {
            "date": today_str,
            "industries": industries,
            "count": len(industries),
        }

        if sector:
            result["sector_filter"] = sector

        return result

    @mcp.tool(
        annotations={
            "title": "Splits Calendar",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def splits_calendar(days_ahead: int = 30) -> dict:
        """Get upcoming stock splits calendar.

        Returns companies with announced stock splits in the specified window.

        Args:
            days_ahead: Number of days to look ahead (default 30, max 90)
        """
        days_ahead = min(max(days_ahead, 1), 90)
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        data = await client.get_safe(
            "/stable/stock-splits-calendar",
            params={
                "from": today.isoformat(),
                "to": end_date.isoformat(),
            },
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        splits_list = data if isinstance(data, list) else []

        if not splits_list:
            return {
                "splits": [],
                "count": 0,
                "period": f"{today.isoformat()} to {end_date.isoformat()}",
            }

        # Sort by date ascending
        splits_list.sort(key=lambda s: s.get("date") or "")

        splits = []
        for s in splits_list:
            num = s.get("numerator")
            den = s.get("denominator")
            label = f"{num}:{den}" if num and den else None

            splits.append({
                "symbol": s.get("symbol"),
                "date": s.get("date"),
                "numerator": num,
                "denominator": den,
                "label": label,
            })

        return {
            "splits": splits,
            "count": len(splits),
            "period": f"{today.isoformat()} to {end_date.isoformat()}",
        }

    @mcp.tool(
        annotations={
            "title": "Sector Valuation",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def sector_valuation() -> dict:
        """Get sector and industry P/E ratio rankings.

        Returns average P/E by sector and industry, showing relative valuation
        across the market. Fetches NYSE + NASDAQ data and averages.
        """
        today_str = date.today().isoformat()

        sector_nyse, sector_nasdaq, industry_nyse, industry_nasdaq = await asyncio.gather(
            client.get_safe(
                "/stable/sector-pe-snapshot",
                params={"date": today_str, "exchange": "NYSE"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/sector-pe-snapshot",
                params={"date": today_str, "exchange": "NASDAQ"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/industry-pe-snapshot",
                params={"date": today_str, "exchange": "NYSE"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
            client.get_safe(
                "/stable/industry-pe-snapshot",
                params={"date": today_str, "exchange": "NASDAQ"},
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        def _avg_pe(nyse_data, nasdaq_data, key_field: str) -> list[dict]:
            """Average PE by name across NYSE and NASDAQ."""
            nyse_list = nyse_data if isinstance(nyse_data, list) else []
            nasdaq_list = nasdaq_data if isinstance(nasdaq_data, list) else []
            pe_vals: dict[str, list[float]] = {}
            for entry in nyse_list + nasdaq_list:
                name = entry.get(key_field)
                pe = entry.get("pe")
                if name and pe is not None and pe > 0:
                    pe_vals.setdefault(name, []).append(pe)
            result = []
            for name, vals in pe_vals.items():
                avg = round(sum(vals) / len(vals), 2)
                result.append({"name": name, "pe": avg})
            result.sort(key=lambda x: x["pe"])
            return result

        sectors = _avg_pe(sector_nyse, sector_nasdaq, "sector")
        industries = _avg_pe(industry_nyse, industry_nasdaq, "industry")

        if not sectors and not industries:
            return {"error": "No sector/industry valuation data available"}

        result: dict = {"date": today_str}

        if sectors:
            result["sectors"] = sectors

        if industries:
            result["top_10_cheapest"] = industries[:10]
            result["top_10_most_expensive"] = industries[-10:][::-1]
            result["total_industries"] = len(industries)

        _warnings = []
        if not sectors:
            _warnings.append("sector PE data unavailable")
        if not industries:
            _warnings.append("industry PE data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result
