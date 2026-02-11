"""Price history and earnings calendar tools."""

from __future__ import annotations

import asyncio
import math
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

        # /stable/historical-price-eod/full returns a flat list of {symbol, date, open, high, low, close, volume, ...}
        history_data, quote_data = await asyncio.gather(
            client.get_safe(
                "/stable/historical-price-eod/full",
                params={
                    "symbol": symbol,
                    "from": from_date.isoformat(),
                    "to": today.isoformat(),
                },
                cache_ttl=client.TTL_12H,
                default=[],
            ),
            client.get_safe(
                "/stable/quote",
                params={"symbol": symbol},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
        )

        quote = _safe_first(quote_data)
        # Stable API returns flat list directly (not nested under "historical")
        historical = history_data if isinstance(history_data, list) else []

        if not quote and not historical:
            return {"error": f"No price data found for '{symbol}'"}

        current_price = quote.get("price")

        # Extract close prices (newest first - API returns newest first)
        closes = [d.get("close") for d in historical if d.get("close")]

        # Build performance across timeframes
        performance = {}
        for perf_period, days in [("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252)]:
            if current_price:
                perf = _calc_performance(current_price, historical, days)
                if perf is not None:
                    performance[perf_period] = perf

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
            "sma_50": quote.get("priceAvg50") or _calc_sma(closes, 50),
            "sma_200": quote.get("priceAvg200") or _calc_sma(closes, 200),
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
        """Get analyst earnings estimates and income statement history for a stock.

        Returns upcoming quarterly estimates (EPS and revenue) from analyst
        consensus, plus recent annual income data for trend context.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        # Use analyst-estimates for per-symbol forward-looking estimates
        # and income-statement for historical actuals
        estimates_data, income_data = await asyncio.gather(
            client.get_safe(
                "/stable/analyst-estimates",
                params={"symbol": symbol, "period": "quarter", "limit": 8},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/income-statement",
                params={"symbol": symbol, "period": "quarter", "limit": 8},
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
        )

        estimates_list = estimates_data if isinstance(estimates_data, list) else []
        income_list = income_data if isinstance(income_data, list) else []

        if not estimates_list and not income_list:
            return {"error": f"No earnings data found for '{symbol}'"}

        # Build forward estimates (sorted by date ascending = nearest first)
        estimates_list.sort(key=lambda e: e.get("date", ""))

        forward_estimates = []
        for entry in estimates_list:
            forward_estimates.append({
                "date": entry.get("date"),
                "eps_avg": entry.get("epsAvg"),
                "eps_high": entry.get("epsHigh"),
                "eps_low": entry.get("epsLow"),
                "revenue_avg": entry.get("revenueAvg"),
                "revenue_high": entry.get("revenueHigh"),
                "revenue_low": entry.get("revenueLow"),
                "num_analysts_eps": entry.get("numAnalystsEps"),
                "num_analysts_revenue": entry.get("numAnalystsRevenue"),
            })

        # Build recent quarterly actuals from income statements
        recent_quarters = []
        for entry in income_list:
            recent_quarters.append({
                "date": entry.get("date"),
                "period": entry.get("period"),
                "revenue": entry.get("revenue"),
                "net_income": entry.get("netIncome"),
                "eps": entry.get("eps"),
                "eps_diluted": entry.get("epsDiluted"),
            })

        result = {
            "symbol": symbol,
            "forward_estimates": forward_estimates,
            "recent_quarters": recent_quarters,
        }

        errors = []
        if not estimates_list:
            errors.append("analyst estimates unavailable")
        if not income_list:
            errors.append("quarterly income data unavailable")
        if errors:
            result["_warnings"] = errors

        return result
