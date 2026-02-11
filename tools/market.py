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
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
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
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
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

    @mcp.tool(
        annotations={
            "title": "Dividends Info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def dividends_info(symbol: str) -> dict:
        """Get dividend history, yield, growth rates, and stock split history.

        Returns current dividend yield, 3Y/5Y dividend CAGR, upcoming ex-date,
        payout context, and stock split history.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()
        sym_params = {"symbol": symbol}

        dividends_data, splits_data, quote_data = await asyncio.gather(
            client.get_safe(
                "/stable/dividends",
                params=sym_params,
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/splits",
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
        )

        div_list = dividends_data if isinstance(dividends_data, list) else []
        split_list = splits_data if isinstance(splits_data, list) else []
        quote = _safe_first(quote_data)

        if not div_list and not split_list:
            return {"error": f"No dividend or split data found for '{symbol}'"}

        # Sort dividends newest first
        div_list.sort(key=lambda d: d.get("date") or "", reverse=True)

        current_price = quote.get("price")

        # Trailing 12-month dividend (sum of most recent 4 payments)
        trailing_annual = None
        if len(div_list) >= 4:
            trailing_annual = round(sum(
                (d.get("dividend") or 0) for d in div_list[:4]
            ), 4)
        elif div_list:
            # If fewer than 4 payments, annualize based on frequency
            freq = div_list[0].get("frequency", "").lower()
            per_payment = div_list[0].get("dividend") or 0
            if "quarter" in freq:
                trailing_annual = round(per_payment * 4, 4)
            elif "semi" in freq or "half" in freq:
                trailing_annual = round(per_payment * 2, 4)
            elif "month" in freq:
                trailing_annual = round(per_payment * 12, 4)
            else:
                trailing_annual = round(per_payment * 4, 4)  # assume quarterly

        # Current yield from trailing annual
        current_yield = None
        if trailing_annual and current_price and current_price > 0:
            current_yield = round(trailing_annual / current_price * 100, 2)

        # Filter dividends to post-split only for CAGR (FMP doesn't adjust for splits)
        split_list.sort(key=lambda s: s.get("date") or "", reverse=True)
        latest_split_date = split_list[0].get("date", "") if split_list else ""
        cagr_divs = [d for d in div_list if (d.get("date") or "") > latest_split_date] if latest_split_date else div_list

        # Build full-year totals using rolling 4-quarter windows for CAGR
        yearly_totals = []
        for i in range(0, len(cagr_divs) - 3, 4):
            chunk = cagr_divs[i:i + 4]
            if len(chunk) == 4:
                total = round(sum((d.get("dividend") or 0) for d in chunk), 4)
                yearly_totals.append(total)

        # Dividend CAGR from rolling annual totals
        def _div_cagr(n_years: int) -> float | None:
            if len(yearly_totals) < n_years + 1:
                return None
            end_val = yearly_totals[0]
            start_val = yearly_totals[n_years]
            if start_val <= 0 or end_val <= 0:
                return None
            try:
                return round(((end_val / start_val) ** (1 / n_years) - 1) * 100, 2)
            except (ZeroDivisionError, ValueError, OverflowError):
                return None

        # Upcoming ex-date (future or very recent)
        today_str = date.today().isoformat()
        upcoming_ex_date = None
        for d in div_list:
            pay_date = d.get("paymentDate") or ""
            ex_date = d.get("date") or ""
            # Show if payment hasn't happened yet or ex-date is within a week
            if pay_date >= today_str or ex_date >= today_str:
                upcoming_ex_date = {
                    "ex_date": ex_date,
                    "dividend": d.get("dividend"),
                    "payment_date": d.get("paymentDate"),
                    "record_date": d.get("recordDate"),
                }
                break

        # Recent dividend history (last 8 payments)
        recent_dividends = []
        for d in div_list[:8]:
            recent_dividends.append({
                "date": d.get("date"),
                "dividend": d.get("dividend"),
                "payment_date": d.get("paymentDate"),
            })

        # Stock splits
        splits = []
        for s in split_list:
            num = s.get("numerator")
            den = s.get("denominator")
            label = f"{num}:{den}" if num and den else None
            splits.append({
                "date": s.get("date"),
                "numerator": num,
                "denominator": den,
                "label": label,
            })

        result = {
            "symbol": symbol,
            "current_price": current_price,
            "trailing_annual_dividend": trailing_annual,
            "dividend_yield_pct": current_yield,
            "dividend_cagr_3y": _div_cagr(3),
            "dividend_cagr_5y": _div_cagr(5),
            "upcoming_ex_date": upcoming_ex_date,
            "recent_dividends": recent_dividends,
            "stock_splits": splits,
        }

        _warnings = []
        if not div_list:
            _warnings.append("dividend data unavailable")
        if not split_list:
            _warnings.append("stock split data unavailable")
        if not quote:
            _warnings.append("quote data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result
