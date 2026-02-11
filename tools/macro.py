"""Macro-economic data tools: treasury rates, economic calendar, market overview."""

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
