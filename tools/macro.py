"""Macro-economic data tools: treasury rates, economic calendar, market overview."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def _safe_first(data: list | None) -> dict:
    if isinstance(data, list) and data:
        return data[0]
    return {}


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Treasury Rates",
            "readOnlyHint": True,
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
        }
    )
    async def market_overview() -> dict:
        """Get today's market snapshot: sector performance, biggest movers, and most active stocks.

        Returns sector rankings, top 5 gainers/losers, and most actively traded names.
        """
        sectors_data, gainers_data, losers_data, actives_data = await asyncio.gather(
            client.get_safe(
                "/stable/sector-performance-snapshot",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/biggest-gainers",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/biggest-losers",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/most-actives",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
        )

        sectors_list = sectors_data if isinstance(sectors_data, list) else []
        gainers_list = gainers_data if isinstance(gainers_data, list) else []
        losers_list = losers_data if isinstance(losers_data, list) else []
        actives_list = actives_data if isinstance(actives_data, list) else []

        if not any([sectors_list, gainers_list, losers_list, actives_list]):
            return {"error": "No market data available"}

        # Sector performance sorted by change %
        sectors = []
        for s in sectors_list:
            sectors.append({
                "sector": s.get("sector"),
                "change_pct": s.get("changesPercentage"),
            })
        sectors.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)

        # Top movers helper
        def _format_mover(m: dict) -> dict:
            return {
                "symbol": m.get("symbol"),
                "name": m.get("name"),
                "price": m.get("price"),
                "change_pct": m.get("changesPercentage"),
            }

        result = {
            "sectors": sectors,
            "top_gainers": [_format_mover(g) for g in gainers_list[:5]],
            "top_losers": [_format_mover(l) for l in losers_list[:5]],
            "most_active": [_format_mover(a) for a in actives_list[:5]],
        }

        _warnings = []
        if not sectors_list:
            _warnings.append("sector performance unavailable")
        if not gainers_list:
            _warnings.append("gainers data unavailable")
        if not losers_list:
            _warnings.append("losers data unavailable")
        if not actives_list:
            _warnings.append("most active data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result
