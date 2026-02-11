"""Price history, earnings calendar, ETF, and technical indicator tools."""

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


def _format_holdings(symbol: str, holdings: list, limit: int) -> dict:
    """Format ETF holdings response."""
    # Sort by weight descending (use 0 as fallback)
    holdings.sort(key=lambda h: h.get("weightPercentage") or 0, reverse=True)
    trimmed = holdings[:limit]

    items = []
    for h in trimmed:
        items.append({
            "symbol": h.get("asset"),
            "name": h.get("name"),
            "weight_pct": h.get("weightPercentage"),
            "shares": h.get("sharesNumber"),
        })

    # Top 10 concentration
    top_10_weights = [h.get("weightPercentage") or 0 for h in holdings[:10]]
    top_10_concentration = round(sum(top_10_weights), 2) if top_10_weights else None

    return {
        "symbol": symbol,
        "mode": "holdings",
        "count": len(items),
        "holdings": items,
        "top_10_concentration_pct": top_10_concentration,
    }


def _format_exposure(symbol: str, exposure: list, limit: int) -> dict:
    """Format ETF exposure response."""
    # Sort by weight descending
    exposure.sort(key=lambda e: e.get("weightPercentage") or 0, reverse=True)
    trimmed = exposure[:limit]

    items = []
    for e in trimmed:
        items.append({
            "etf_symbol": e.get("etfSymbol"),
            "etf_name": e.get("etfName"),  # may not exist — will verify live
            "weight_pct": e.get("weightPercentage"),
        })

    return {
        "symbol": symbol,
        "mode": "exposure",
        "count": len(items),
        "etf_holders": items,
    }


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

    @mcp.tool(
        annotations={
            "title": "Earnings Calendar",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def earnings_calendar(
        symbol: str | None = None,
        days_ahead: int = 7,
    ) -> dict:
        """Get upcoming earnings report dates and estimates.

        Returns companies reporting earnings within the specified window.
        Optionally filter to a specific ticker to find its next report date.

        Args:
            symbol: Optional stock ticker to filter results (e.g. "AAPL")
            days_ahead: Number of days to look ahead (default 7, max 30)
        """
        days_ahead = max(1, min(days_ahead, 30))
        today = date.today()
        to_date = today + timedelta(days=days_ahead)

        data = await client.get_safe(
            "/stable/earnings-calendar",
            params={
                "from": today.isoformat(),
                "to": to_date.isoformat(),
            },
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        entries = data if isinstance(data, list) else []

        # Client-side filter if symbol specified
        if symbol:
            symbol = symbol.upper().strip()
            entries = [e for e in entries if e.get("symbol", "").upper() == symbol]

        if not entries:
            msg = f"No earnings scheduled in the next {days_ahead} days"
            if symbol:
                msg += f" for '{symbol}'"
            return {"error": msg}

        # Sort by date ascending
        entries.sort(key=lambda e: e.get("date") or "")

        earnings = []
        for e in entries:
            earnings.append({
                "symbol": e.get("symbol"),
                "date": e.get("date"),
                "time": e.get("time"),  # "amc" / "bmo" / "--"
                "fiscal_date_ending": e.get("fiscalDateEnding"),
                "eps_estimate": e.get("epsEstimated"),
                "revenue_estimate": e.get("revenueEstimated"),
                "eps_actual": e.get("eps"),
                "revenue_actual": e.get("revenue"),
            })

        return {
            "from_date": today.isoformat(),
            "to_date": to_date.isoformat(),
            "symbol": symbol if symbol else None,
            "count": len(earnings),
            "earnings": earnings,
        }

    @mcp.tool(
        annotations={
            "title": "ETF Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def etf_lookup(
        symbol: str,
        mode: str = "auto",
        limit: int = 25,
    ) -> dict:
        """Look up ETF holdings or find which ETFs hold a stock.

        Dual-mode tool: pass an ETF ticker to see its holdings, or a stock
        ticker to see which ETFs hold it. Use mode="auto" to detect automatically.

        Args:
            symbol: ETF ticker (e.g. "QQQ") or stock ticker (e.g. "AAPL")
            mode: "holdings" (what's inside this ETF), "exposure" (which ETFs hold this stock), or "auto" (try both)
            limit: Max results to return (default 25)
        """
        symbol = symbol.upper().strip()
        limit = max(1, min(limit, 100))

        if mode not in ("holdings", "exposure", "auto"):
            return {"error": f"Invalid mode '{mode}'. Use: holdings, exposure, auto"}

        async def _try_holdings() -> list | None:
            data = await client.get_safe(
                "/stable/etf-holdings",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            )
            result = data if isinstance(data, list) else []
            return result if result else None

        async def _try_exposure() -> list | None:
            data = await client.get_safe(
                "/stable/etf-stock-exposure",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            )
            result = data if isinstance(data, list) else []
            return result if result else None

        if mode == "holdings":
            holdings = await _try_holdings()
            if not holdings:
                return {"error": f"No ETF holdings found for '{symbol}'. Is it an ETF ticker?"}
            return _format_holdings(symbol, holdings, limit)

        if mode == "exposure":
            exposure = await _try_exposure()
            if not exposure:
                return {"error": f"No ETF exposure found for '{symbol}'. Is it a stock ticker?"}
            return _format_exposure(symbol, exposure, limit)

        # Auto mode: try both in parallel
        holdings, exposure = await asyncio.gather(
            _try_holdings(),
            _try_exposure(),
        )

        if holdings:
            return _format_holdings(symbol, holdings, limit)
        if exposure:
            return _format_exposure(symbol, exposure, limit)

        return {"error": f"No ETF data found for '{symbol}'. Try specifying mode='holdings' or mode='exposure'."}

    VALID_INDICATORS = {"sma", "ema", "rsi", "adx", "wma", "dema", "tema", "williams", "standarddeviation"}

    @mcp.tool(
        annotations={
            "title": "Technical Indicators",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def technical_indicators(
        symbol: str,
        indicator: str = "rsi",
        period_length: int = 14,
        timeframe: str = "1day",
    ) -> dict:
        """Get technical indicator values for a stock.

        Supports SMA, EMA, RSI, ADX, WMA, DEMA, TEMA, Williams %R,
        and Standard Deviation. Returns last 30 data points.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            indicator: Indicator type - sma, ema, rsi, adx, wma, dema, tema, williams, standarddeviation
            period_length: Lookback period (default 14)
            timeframe: Data timeframe - "1day", "1hour", "4hour", "1week" (default "1day")
        """
        symbol = symbol.upper().strip()
        indicator = indicator.lower().strip()

        if indicator not in VALID_INDICATORS:
            return {"error": f"Invalid indicator '{indicator}'. Use: {', '.join(sorted(VALID_INDICATORS))}"}

        data = await client.get_safe(
            f"/stable/technical-indicators/{indicator}",
            params={
                "symbol": symbol,
                "periodLength": period_length,
                "timeframe": timeframe,
            },
            cache_ttl=client.TTL_HOURLY,
            default=[],
        )

        data_list = data if isinstance(data, list) else []

        if not data_list:
            return {"error": f"No {indicator.upper()} data found for '{symbol}'"}

        # Return last 30 data points, newest first
        trimmed = data_list[:30]

        values = []
        for d in trimmed:
            entry = {
                "date": d.get("date"),
                "close": d.get("close"),
                indicator: d.get(indicator),
            }
            values.append(entry)

        current_value = values[0].get(indicator) if values else None

        return {
            "symbol": symbol,
            "indicator": indicator,
            "period_length": period_length,
            "timeframe": timeframe,
            "current_value": current_value,
            "data_points": len(values),
            "values": values,
        }
