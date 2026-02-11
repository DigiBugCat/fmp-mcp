"""Price history and earnings calendar tools."""

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


PERIOD_DAYS = {
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "ytd": None,  # calculated
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


def _calc_sma(prices: list[float], window: int) -> float | None:
    """Calculate simple moving average from a list of prices."""
    if len(prices) < window:
        return None
    return round(sum(prices[:window]) / window, 2)


def _calc_performance(current: float, history: list[dict], days: int) -> float | None:
    """Calculate % performance over N days from daily history (newest first)."""
    if not current or len(history) < days:
        return None
    old_price = history[min(days - 1, len(history) - 1)].get("close")
    if not old_price or old_price == 0:
        return None
    return round((current / old_price - 1) * 100, 2)


def _calc_volatility(history: list[dict], window: int = 30) -> float | None:
    """Calculate annualized daily volatility from close prices."""
    closes = [d.get("close") for d in history[:window] if d.get("close")]
    if len(closes) < 2:
        return None
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] != 0:
            returns.append(closes[i] / closes[i - 1] - 1)
    if not returns:
        return None
    import math
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance)
    return round(daily_vol * math.sqrt(252) * 100, 2)


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Price History",
            "readOnlyHint": True,
        }
    )
    async def price_history(
        symbol: str,
        period: str = "1y",
    ) -> dict:
        """Get price performance, key levels, and momentum indicators.

        Returns current price, 52-week range, SMA-50/200, performance across
        timeframes, volatility, and recent daily closes. Not for raw chart data.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            period: Time period - "1w", "1m", "3m", "6m", "ytd", "1y", "2y", "5y" (default "1y")
        """
        symbol = symbol.upper().strip()

        if period not in PERIOD_DAYS:
            return {"error": f"Invalid period '{period}'. Use: {', '.join(PERIOD_DAYS.keys())}"}

        # Calculate date range
        today = date.today()
        if period == "ytd":
            from_date = date(today.year, 1, 1)
        else:
            from_date = today - timedelta(days=PERIOD_DAYS[period])

        history_data, quote_data = await asyncio.gather(
            client.get_safe(
                f"/api/v3/historical-price-full/{symbol}",
                params={"from": from_date.isoformat(), "to": today.isoformat()},
                cache_ttl=client.TTL_12H,
                default={},
            ),
            client.get_safe(
                f"/api/v3/quote/{symbol}",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
        )

        quote = _safe_first(quote_data)
        historical = []
        if isinstance(history_data, dict):
            historical = history_data.get("historical", [])

        if not quote and not historical:
            return {"error": f"No price data found for '{symbol}'"}

        current_price = quote.get("price")

        # Extract close prices (newest first)
        closes = [d.get("close") for d in historical if d.get("close")]

        # Build performance across timeframes
        performance = {}
        for perf_period, days in [("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("ytd", None), ("1y", 252)]:
            if perf_period == "ytd":
                # Find first trading day of year
                ytd_days = None
                for i, d in enumerate(historical):
                    if d.get("date", "").startswith(str(today.year - 1)):
                        ytd_days = i
                        break
                if ytd_days and current_price:
                    performance["ytd"] = _calc_performance(current_price, historical, ytd_days)
            elif current_price:
                performance[perf_period] = _calc_performance(current_price, historical, days)

        # Recent 30 daily closes for context
        recent_closes = [
            {"date": d.get("date"), "close": d.get("close"), "volume": d.get("volume")}
            for d in historical[:30]
        ]

        result = {
            "symbol": symbol,
            "current_price": current_price,
            "year_high": quote.get("yearHigh"),
            "year_low": quote.get("yearLow"),
            "sma_50": _calc_sma(closes, 50),
            "sma_200": _calc_sma(closes, 200),
            "performance_pct": performance,
            "daily_volatility_annualized_pct": _calc_volatility(historical),
            "recent_closes": recent_closes,
            "data_points": len(historical),
        }

        errors = []
        if not quote:
            errors.append("quote data unavailable")
        if not historical:
            errors.append("historical data unavailable")
        if errors:
            result["_warnings"] = errors

        return result

    @mcp.tool(
        annotations={
            "title": "Earnings Info",
            "readOnlyHint": True,
        }
    )
    async def earnings_info(symbol: str) -> dict:
        """Check earnings dates, estimates, and recent surprise history.

        Returns next earnings date/estimates and last 8 quarters of EPS
        surprises and revenue vs estimates.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        # Get upcoming and historical earnings
        # The earning_calendar endpoint returns upcoming dates
        # The historical endpoint returns past earnings with actuals vs estimates
        upcoming_data, historical_data = await asyncio.gather(
            client.get_safe(
                f"/api/v3/earning_calendar",
                params={"symbol": symbol},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                f"/api/v3/historical/earning_calendar/{symbol}",
                params={"limit": 8},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
        )

        upcoming_list = upcoming_data if isinstance(upcoming_data, list) else []
        historical_list = historical_data if isinstance(historical_data, list) else []

        if not upcoming_list and not historical_list:
            return {"error": f"No earnings data found for '{symbol}'"}

        # Find next earnings from upcoming (filter for this symbol)
        next_earnings = None
        for entry in upcoming_list:
            if entry.get("symbol", "").upper() == symbol:
                next_earnings = {
                    "date": entry.get("date"),
                    "eps_estimate": entry.get("epsEstimated"),
                    "revenue_estimate": entry.get("revenueEstimated"),
                    "fiscal_period": entry.get("fiscalDateEnding"),
                    "time": entry.get("time"),  # "bmo" (before market open) or "amc" (after market close)
                }
                break

        # Build earnings history with surprises
        history = []
        for entry in historical_list:
            eps_actual = entry.get("eps")
            eps_estimate = entry.get("epsEstimated")
            revenue_actual = entry.get("revenue")
            revenue_estimate = entry.get("revenueEstimated")

            eps_surprise = None
            eps_surprise_pct = None
            if eps_actual is not None and eps_estimate is not None:
                eps_surprise = round(eps_actual - eps_estimate, 4)
                if eps_estimate != 0:
                    eps_surprise_pct = round((eps_actual / eps_estimate - 1) * 100, 2)

            revenue_surprise_pct = None
            if revenue_actual and revenue_estimate and revenue_estimate != 0:
                revenue_surprise_pct = round((revenue_actual / revenue_estimate - 1) * 100, 2)

            history.append({
                "date": entry.get("date"),
                "fiscal_period": entry.get("fiscalDateEnding"),
                "eps_actual": eps_actual,
                "eps_estimate": eps_estimate,
                "eps_surprise": eps_surprise,
                "eps_surprise_pct": eps_surprise_pct,
                "revenue_actual": revenue_actual,
                "revenue_estimate": revenue_estimate,
                "revenue_surprise_pct": revenue_surprise_pct,
            })

        # Summarize surprise track record
        beats = sum(1 for h in history if h.get("eps_surprise") and h["eps_surprise"] > 0)
        misses = sum(1 for h in history if h.get("eps_surprise") and h["eps_surprise"] < 0)
        meets = sum(1 for h in history if h.get("eps_surprise") is not None and h["eps_surprise"] == 0)

        result = {
            "symbol": symbol,
            "next_earnings": next_earnings,
            "earnings_history": history,
            "surprise_summary": {
                "quarters_reported": len(history),
                "beats": beats,
                "misses": misses,
                "meets": meets,
            },
        }

        errors = []
        if not upcoming_list:
            errors.append("upcoming earnings data unavailable")
        if not historical_list:
            errors.append("historical earnings data unavailable")
        if errors:
            result["_warnings"] = errors

        return result
