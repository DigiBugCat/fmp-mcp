"""Insider activity and institutional ownership tools."""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient

FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"


def _safe_first(data: list | None) -> dict:
    if isinstance(data, list) and data:
        return data[0]
    return {}


def _latest_quarter() -> tuple[int, int]:
    """Return the most recently completed quarter's (year, quarter)."""
    today = date.today()
    month = today.month
    year = today.year
    if month <= 3:
        return year - 1, 4
    elif month <= 6:
        return year, 1
    elif month <= 9:
        return year, 2
    else:
        return year, 3


def _short_interest_dates() -> list[str]:
    """Generate candidate FINRA settlement dates (15th + last biz day).

    FINRA publishes short interest on the 15th and last business day
    of each month. We generate ~6 candidates (current + 2 prior months),
    filter out future dates, and sort descending (newest first).
    """
    today = date.today()
    candidates: list[date] = []

    for months_back in range(3):
        # Walk back months
        month = today.month - months_back
        year = today.year
        while month < 1:
            month += 12
            year -= 1

        # 15th of the month
        candidates.append(date(year, month, 15))

        # Last business day of the month
        last_day = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day)
        while d.weekday() >= 5:  # Sat=5, Sun=6
            d -= timedelta(days=1)
        candidates.append(d)

    # Filter future dates and sort newest first
    candidates = [d for d in candidates if d <= today]
    candidates.sort(reverse=True)
    return [d.isoformat() for d in candidates]


async def _fetch_finra_short_interest(symbol: str, settlement_date: str) -> dict | None:
    """Fetch FINRA consolidated short interest for one settlement date.

    Returns the first matching record, or None if no data (204 or empty).
    """
    payload = {
        "fields": [
            "settlementDate",
            "currentShortPositionQuantity",
            "previousShortPositionQuantity",
            "changePreviousNumber",
            "changePercent",
            "averageDailyVolumeQuantity",
            "daysToCoverQuantity",
        ],
        "dateRangeFilters": [
            {"fieldName": "settlementDate", "startDate": settlement_date, "endDate": settlement_date}
        ],
        "domainFilters": [
            {"fieldName": "symbolCode", "values": [symbol]}
        ],
        "limit": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(FINRA_URL, json=payload)
        if resp.status_code == 204 or not resp.content:
            return None
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except (httpx.HTTPError, ValueError):
        return None


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Insider Activity",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def insider_activity(symbol: str) -> dict:
        """Get insider trading activity, statistics, and ownership context.

        Returns net buy/sell over 30/90 days, cluster buying signals,
        CEO/CFO action highlights, and insider ownership as % of float.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()
        sym_params = {"symbol": symbol}

        trades_data, stats_data, float_data = await asyncio.gather(
            client.get_safe(
                "/stable/insider-trading/search",
                params={**sym_params, "limit": 100},
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                "/stable/insider-trading/statistics",
                params=sym_params,
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                "/stable/shares-float",
                params=sym_params,
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        trades_list = trades_data if isinstance(trades_data, list) else []
        stats = _safe_first(stats_data)
        float_info = _safe_first(float_data)

        if not trades_list and not stats:
            return {"error": f"No insider data found for '{symbol}'"}

        # Analyze trades over 30/90 day windows
        today = date.today()
        cutoff_30 = (today - timedelta(days=30)).isoformat()
        cutoff_90 = (today - timedelta(days=90)).isoformat()

        buys_30, sells_30, buys_90, sells_90 = 0, 0, 0, 0
        cluster_buyers = {}  # Track unique buyers in 30-day window
        notable_trades = []

        for trade in trades_list:
            trade_date = trade.get("filingDate", trade.get("transactionDate", ""))
            tx_type = (trade.get("transactionType") or "").lower()
            shares = trade.get("securitiesTransacted") or 0
            price = trade.get("price") or 0
            name = trade.get("reportingName", "")
            title = trade.get("typeOfOwner", "")

            is_buy = "purchase" in tx_type or "p-purchase" in tx_type
            is_sell = "sale" in tx_type or "s-sale" in tx_type

            if trade_date >= cutoff_90:
                if is_buy:
                    buys_90 += shares
                elif is_sell:
                    sells_90 += shares

                if trade_date >= cutoff_30:
                    if is_buy:
                        buys_30 += shares
                        cluster_buyers[name] = cluster_buyers.get(name, 0) + 1
                    elif is_sell:
                        sells_30 += shares

            # Highlight C-suite trades
            title_lower = title.lower() if title else ""
            if any(t in title_lower for t in ["ceo", "cfo", "coo", "director", "officer"]):
                if is_buy or is_sell:
                    notable_trades.append({
                        "name": name,
                        "title": title,
                        "type": "buy" if is_buy else "sell",
                        "shares": shares,
                        "price": price,
                        "date": trade_date,
                        "value": round(shares * price, 2) if shares and price else None,
                    })

        # Cluster buying: 3+ unique insiders buying within 30 days
        cluster_buying = len([b for b in cluster_buyers.values() if b > 0]) >= 3

        # Insider ownership % of float
        shares_float = float_info.get("floatShares")
        insider_ownership_pct = None
        if shares_float and shares_float > 0:
            outstanding = float_info.get("outstandingShares")
            if outstanding and shares_float:
                insider_ownership_pct = round(
                    (1 - shares_float / outstanding) * 100, 2
                ) if outstanding > shares_float else None

        # Stats use different field names in /stable/ API
        total_acquired = stats.get("totalAcquired") or stats.get("totalBought")
        total_disposed = stats.get("totalDisposed") or stats.get("totalSold")
        acquired_count = stats.get("acquiredTransactions") or stats.get("buyCount")
        disposed_count = stats.get("disposedTransactions") or stats.get("sellCount")

        result = {
            "symbol": symbol,
            "net_activity_30d": {
                "shares_bought": buys_30,
                "shares_sold": sells_30,
                "net_shares": buys_30 - sells_30,
                "signal": "net_buying" if buys_30 > sells_30 else "net_selling" if sells_30 > buys_30 else "neutral",
            },
            "net_activity_90d": {
                "shares_bought": buys_90,
                "shares_sold": sells_90,
                "net_shares": buys_90 - sells_90,
            },
            "cluster_buying": cluster_buying,
            "statistics": {
                "total_bought": total_acquired,
                "total_sold": total_disposed,
                "buy_count": acquired_count,
                "sell_count": disposed_count,
            },
            "notable_trades": notable_trades[:10],
            "float_context": {
                "float_shares": shares_float,
                "outstanding_shares": float_info.get("outstandingShares"),
                "insider_ownership_pct": insider_ownership_pct,
            },
        }

        _warnings = []
        if not trades_list:
            _warnings.append("insider trades unavailable")
        if not stats:
            _warnings.append("insider statistics unavailable")
        if not float_info:
            _warnings.append("float data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Institutional Ownership",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def institutional_ownership(symbol: str) -> dict:
        """Get institutional ownership breakdown and position changes.

        Returns top 10 holders with % ownership, quarter-over-quarter
        position changes, and institutional vs float ratio.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()
        sym_params = {"symbol": symbol}
        year, quarter = _latest_quarter()

        summary_data, holders_data, float_data = await asyncio.gather(
            client.get_safe(
                "/stable/institutional-ownership/symbol-positions-summary",
                params={**sym_params, "year": year, "quarter": quarter},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/institutional-ownership/extract-analytics/holder",
                params={**sym_params, "year": year, "quarter": quarter, "limit": 20},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/shares-float",
                params=sym_params,
                cache_ttl=client.TTL_DAILY,
                default=[],
            ),
        )

        summary_list = summary_data if isinstance(summary_data, list) else []
        holders_list = holders_data if isinstance(holders_data, list) else []
        float_info = _safe_first(float_data)

        if not summary_list and not holders_list:
            return {"error": f"No institutional ownership data found for '{symbol}'"}

        # Top holders with ownership %
        outstanding = float_info.get("outstandingShares") or 0
        top_holders = []
        for h in holders_list[:10]:
            shares = h.get("sharesNumber") or h.get("shares") or 0
            pct = round(shares / outstanding * 100, 2) if outstanding > 0 else None
            change = h.get("changeInSharesNumber") or h.get("changeInShares") or 0
            top_holders.append({
                "holder": h.get("investorName") or h.get("name") or h.get("holder"),
                "shares": shares,
                "ownership_pct": pct,
                "change_in_shares": change,
                "change_type": "increased" if change > 0 else "decreased" if change < 0 else "unchanged",
                "date_reported": h.get("date") or h.get("dateReported"),
            })

        # Aggregate position changes from summary
        summary = _safe_first(summary_list)
        investors_holding = summary.get("investorsHolding", 0)
        investors_change = summary.get("investorsHoldingChange", 0)
        total_institutional_shares = summary.get("numberOf13Fshares", 0)
        ownership_pct = summary.get("ownershipPercent", 0)

        # Institutional ownership as % of float
        float_shares = float_info.get("floatShares") or 0
        institutional_pct_of_float = None
        if total_institutional_shares and float_shares > 0:
            institutional_pct_of_float = round(
                total_institutional_shares / float_shares * 100, 2
            )

        result = {
            "symbol": symbol,
            "reporting_period": f"Q{quarter} {year}",
            "top_holders": top_holders,
            "position_changes": {
                "investors_holding": investors_holding,
                "investors_change": investors_change,
                "ownership_pct": ownership_pct,
            },
            "ownership_summary": {
                "total_institutional_shares": total_institutional_shares,
                "float_shares": float_shares,
                "institutional_pct_of_float": institutional_pct_of_float,
                "outstanding_shares": outstanding,
            },
        }

        _warnings = []
        if not summary_list:
            _warnings.append("ownership summary unavailable")
        if not holders_list:
            _warnings.append("holder details unavailable")
        if not float_info:
            _warnings.append("float data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    @mcp.tool(
        annotations={
            "title": "Short Interest",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def short_interest(symbol: str) -> dict:
        """Get short interest data with float context.

        Combines FINRA consolidated short interest (free, no API key)
        with FMP shares-float to compute short % of float and outstanding.

        Returns shares short, days to cover, change vs prior period,
        and short as % of float/outstanding.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        candidates = _short_interest_dates()
        finra_tasks = [_fetch_finra_short_interest(symbol, d) for d in candidates]
        float_task = client.get_safe(
            "/stable/shares-float",
            params={"symbol": symbol},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        all_results = await asyncio.gather(*finra_tasks, float_task)
        finra_results = all_results[:-1]
        float_data = all_results[-1]

        # Take first non-None FINRA result (candidates sorted newest-first)
        finra = None
        for r in finra_results:
            if r is not None:
                finra = r
                break

        float_info = _safe_first(float_data)

        if finra is None and not float_info:
            return {"error": f"No short interest or float data found for '{symbol}'"}

        result: dict = {"symbol": symbol}

        if finra is not None:
            result["settlement_date"] = finra.get("settlementDate")
            result["short_interest"] = {
                "shares_short": finra.get("currentShortPositionQuantity"),
                "previous_shares_short": finra.get("previousShortPositionQuantity"),
                "change_pct": finra.get("changePercent"),
                "avg_daily_volume": finra.get("averageDailyVolumeQuantity"),
                "days_to_cover": finra.get("daysToCoverQuantity"),
            }

        if float_info:
            float_shares = float_info.get("floatShares")
            outstanding = float_info.get("outstandingShares")
            shares_short = (finra or {}).get("currentShortPositionQuantity")

            short_pct_of_float = None
            short_pct_of_outstanding = None
            if shares_short and float_shares and float_shares > 0:
                short_pct_of_float = round(shares_short / float_shares * 100, 2)
            if shares_short and outstanding and outstanding > 0:
                short_pct_of_outstanding = round(shares_short / outstanding * 100, 2)

            result["float_context"] = {
                "float_shares": float_shares,
                "outstanding_shares": outstanding,
                "short_pct_of_float": short_pct_of_float,
                "short_pct_of_outstanding": short_pct_of_outstanding,
            }

        _warnings = []
        if finra is None:
            _warnings.append("FINRA short interest unavailable")
        if not float_info:
            _warnings.append("float data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result
