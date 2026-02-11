"""Financial statements and growth tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def _calc_cagr(start_val: float | None, end_val: float | None, years: int) -> float | None:
    """Calculate compound annual growth rate."""
    if not start_val or not end_val or years <= 0:
        return None
    if start_val <= 0 or end_val <= 0:
        return None
    try:
        return round(((end_val / start_val) ** (1 / years) - 1) * 100, 2)
    except (ZeroDivisionError, ValueError, OverflowError):
        return None


def _simplify_period(income: dict, balance: dict, cashflow: dict) -> dict:
    """Extract key metrics from a single period across all three statements."""
    return {
        "date": income.get("date") or balance.get("date") or cashflow.get("date"),
        "period": income.get("period") or balance.get("period"),
        # Income statement
        "revenue": income.get("revenue"),
        "gross_profit": income.get("grossProfit"),
        "operating_income": income.get("operatingIncome"),
        "net_income": income.get("netIncome"),
        "eps": income.get("eps"),
        "eps_diluted": income.get("epsdiluted"),
        "gross_margin": _pct(income.get("grossProfit"), income.get("revenue")),
        "operating_margin": _pct(income.get("operatingIncome"), income.get("revenue")),
        "net_margin": _pct(income.get("netIncome"), income.get("revenue")),
        # Balance sheet
        "total_assets": balance.get("totalAssets"),
        "total_liabilities": balance.get("totalLiabilities"),
        "total_equity": balance.get("totalStockholdersEquity"),
        "total_debt": balance.get("totalDebt"),
        "cash_and_equivalents": balance.get("cashAndCashEquivalents"),
        "net_debt": balance.get("netDebt"),
        # Cash flow
        "operating_cash_flow": cashflow.get("operatingCashFlow"),
        "capex": cashflow.get("capitalExpenditure"),
        "free_cash_flow": cashflow.get("freeCashFlow"),
        "dividends_paid": cashflow.get("dividendsPaid"),
        "share_buybacks": cashflow.get("commonStockRepurchased"),
    }


def _pct(numerator, denominator) -> float | None:
    """Calculate percentage safely."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Financial Statements",
            "readOnlyHint": True,
        }
    )
    async def financial_statements(
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> dict:
        """Get income statement, balance sheet, and cash flow data with growth rates.

        Returns simplified per-period financials and 3-year CAGRs for key metrics.
        Use after company_overview for deeper analysis.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            period: "annual" or "quarter" (default "annual")
            limit: Number of periods to return (default 5)
        """
        symbol = symbol.upper().strip()
        params = {"period": period, "limit": limit}

        income_data, balance_data, cashflow_data = await asyncio.gather(
            client.get_safe(
                f"/api/v3/income-statement/{symbol}",
                params=params,
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                f"/api/v3/balance-sheet-statement/{symbol}",
                params=params,
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
            client.get_safe(
                f"/api/v3/cash-flow-statement/{symbol}",
                params=params,
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
        )

        if not income_data and not balance_data and not cashflow_data:
            return {"error": f"No financial data found for '{symbol}'"}

        # Ensure lists
        income_list = income_data if isinstance(income_data, list) else []
        balance_list = balance_data if isinstance(balance_data, list) else []
        cashflow_list = cashflow_data if isinstance(cashflow_data, list) else []

        # Build indexed lookups by date
        balance_by_date = {b["date"]: b for b in balance_list}
        cashflow_by_date = {c["date"]: c for c in cashflow_list}

        # Build simplified periods (income-statement-led since it's most complete)
        periods = []
        for inc in income_list:
            date = inc.get("date", "")
            bal = balance_by_date.get(date, {})
            cf = cashflow_by_date.get(date, {})
            periods.append(_simplify_period(inc, bal, cf))

        # Calculate 3-year CAGRs if we have enough data
        # Data is newest-first, so index 0 = latest, index 3 = 3 years ago
        growth = {}
        if len(periods) >= 4:
            latest = periods[0]
            three_yr = periods[3]
            growth = {
                "revenue_cagr_3y": _calc_cagr(
                    three_yr.get("revenue"), latest.get("revenue"), 3
                ),
                "net_income_cagr_3y": _calc_cagr(
                    three_yr.get("net_income"), latest.get("net_income"), 3
                ),
                "fcf_cagr_3y": _calc_cagr(
                    three_yr.get("free_cash_flow"), latest.get("free_cash_flow"), 3
                ),
                "eps_cagr_3y": _calc_cagr(
                    three_yr.get("eps_diluted"), latest.get("eps_diluted"), 3
                ),
            }

        result = {
            "symbol": symbol,
            "period_type": period,
            "periods": periods,
        }
        if growth:
            result["growth_3y_cagr"] = growth

        # Flag partial data
        errors = []
        if not income_list:
            errors.append("income statement unavailable")
        if not balance_list:
            errors.append("balance sheet unavailable")
        if not cashflow_list:
            errors.append("cash flow statement unavailable")
        if errors:
            result["_warnings"] = errors

        return result
