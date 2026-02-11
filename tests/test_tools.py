"""Tests for FMP MCP server tools using respx mocking."""

from __future__ import annotations

import json

import pytest
import respx
import httpx

from fastmcp import FastMCP, Client
from fmp_client import FMPClient, FMPError
from tests.conftest import (
    AAPL_PROFILE, AAPL_QUOTE, AAPL_RATIOS,
    AAPL_INCOME, AAPL_BALANCE, AAPL_CASHFLOW,
    AAPL_PRICE_TARGET, AAPL_GRADES, AAPL_RATING,
    AAPL_SEARCH, AAPL_HISTORICAL,
    AAPL_EARNINGS_UPCOMING, AAPL_EARNINGS_HISTORICAL,
)
from tools.overview import register as register_overview
from tools.financials import register as register_financials
from tools.valuation import register as register_valuation
from tools.market import register as register_market


# --- FMPClient Tests ---


class TestFMPClient:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_api, fmp_client):
        mock_api.get("/api/v3/profile/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        result = await fmp_client.get("/api/v3/profile/AAPL")
        assert result[0]["companyName"] == "Apple Inc."

    @pytest.mark.asyncio
    async def test_get_caching(self, mock_api, fmp_client):
        route = mock_api.get("/api/v3/profile/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        # First call hits the API
        await fmp_client.get("/api/v3/profile/AAPL", cache_ttl=300)
        # Second call should use cache
        await fmp_client.get("/api/v3/profile/AAPL", cache_ttl=300)
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_get_error_message(self, mock_api, fmp_client):
        mock_api.get("/api/v3/profile/INVALID").mock(
            return_value=httpx.Response(200, json={"Error Message": "Invalid API KEY."})
        )
        with pytest.raises(FMPError, match="Invalid API KEY"):
            await fmp_client.get("/api/v3/profile/INVALID")

    @pytest.mark.asyncio
    async def test_get_http_error(self, mock_api, fmp_client):
        mock_api.get("/api/v3/profile/AAPL").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        with pytest.raises(FMPError, match="429"):
            await fmp_client.get("/api/v3/profile/AAPL")

    @pytest.mark.asyncio
    async def test_get_safe_returns_default(self, mock_api, fmp_client):
        mock_api.get("/api/v3/profile/BAD").mock(
            return_value=httpx.Response(404, text="Not found")
        )
        result = await fmp_client.get_safe("/api/v3/profile/BAD", default=[])
        assert result == []


# --- Tool Integration Tests (via FastMCP Client) ---


def _make_server(register_fn) -> tuple[FastMCP, FMPClient]:
    """Create a FastMCP server with registered tools."""
    mcp = FastMCP("Test")
    client = FMPClient(api_key="test_key")
    register_fn(mcp, client)
    return mcp, client


class TestCompanyOverview:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_overview(self):
        respx.get("https://financialmodelingprep.com/api/v3/profile/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/quote/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_QUOTE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/ratios-ttm/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_RATIOS)
        )

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["price"] == 189.84
        assert data["ratios"]["pe_ttm"] == 29.57
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_data(self):
        """Should return partial data with warnings when some endpoints fail."""
        respx.get("https://financialmodelingprep.com/api/v3/profile/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/quote/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_QUOTE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/ratios-ttm/AAPL").mock(
            return_value=httpx.Response(500, text="error")
        )

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "AAPL"})

        data = result.data
        assert data["name"] == "Apple Inc."
        assert data["_warnings"] == ["ratio data unavailable"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get("https://financialmodelingprep.com/api/v3/profile/ZZZZ").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://financialmodelingprep.com/api/v3/quote/ZZZZ").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://financialmodelingprep.com/api/v3/ratios-ttm/ZZZZ").mock(
            return_value=httpx.Response(200, json=[])
        )

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestStockSearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_simple_search(self):
        respx.get("https://financialmodelingprep.com/api/v3/search").mock(
            return_value=httpx.Response(200, json=AAPL_SEARCH)
        )

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_search", {"query": "apple"})

        data = result.data
        assert data["count"] == 2
        assert data["results"][0]["symbol"] == "AAPL"
        await fmp.close()


class TestFinancialStatements:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_financials(self):
        respx.get("https://financialmodelingprep.com/api/v3/income-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_INCOME)
        )
        respx.get("https://financialmodelingprep.com/api/v3/balance-sheet-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_BALANCE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/cash-flow-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_CASHFLOW)
        )

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["periods"]) == 4
        assert data["periods"][0]["revenue"] == 391035000000
        assert data["periods"][0]["free_cash_flow"] == 108295000000
        # Should have 3-year CAGR since we have 4 periods
        assert "growth_3y_cagr" in data
        assert data["growth_3y_cagr"]["revenue_cagr_3y"] is not None
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_margins_calculated(self):
        respx.get("https://financialmodelingprep.com/api/v3/income-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_INCOME)
        )
        respx.get("https://financialmodelingprep.com/api/v3/balance-sheet-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_BALANCE)
        )
        respx.get("https://financialmodelingprep.com/api/v3/cash-flow-statement/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_CASHFLOW)
        )

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "AAPL"})

        data = result.data
        p = data["periods"][0]
        assert p["gross_margin"] is not None
        assert p["gross_margin"] > 40  # Apple's gross margin is ~46%
        await fmp.close()


class TestAnalystConsensus:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_consensus(self):
        respx.get("https://financialmodelingprep.com/stable/price-target-consensus").mock(
            return_value=httpx.Response(200, json=AAPL_PRICE_TARGET)
        )
        respx.get("https://financialmodelingprep.com/stable/upgrades-downgrades-consensus").mock(
            return_value=httpx.Response(200, json=AAPL_GRADES)
        )
        respx.get("https://financialmodelingprep.com/stable/ratings-snapshot").mock(
            return_value=httpx.Response(200, json=AAPL_RATING)
        )
        respx.get("https://financialmodelingprep.com/api/v3/quote/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_QUOTE)
        )

        mcp, fmp = _make_server(register_valuation)
        async with Client(mcp) as c:
            result = await c.call_tool("analyst_consensus", {"symbol": "AAPL"})

        data = result.data
        assert data["price_targets"]["consensus"] == 210.50
        assert data["price_targets"]["upside_pct"] is not None
        assert data["analyst_grades"]["buy"] == 25
        assert data["fmp_rating"]["rating"] == "S"
        await fmp.close()


class TestPriceHistory:
    @pytest.mark.asyncio
    @respx.mock
    async def test_price_history(self):
        respx.get("https://financialmodelingprep.com/api/v3/historical-price-full/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_HISTORICAL)
        )
        respx.get("https://financialmodelingprep.com/api/v3/quote/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_QUOTE)
        )

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("price_history", {"symbol": "AAPL"})

        data = result.data
        assert data["current_price"] == 189.84
        assert data["year_high"] == 199.62
        assert len(data["recent_closes"]) <= 30
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_invalid_period(self):
        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("price_history", {"symbol": "AAPL", "period": "10y"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestEarningsInfo:
    @pytest.mark.asyncio
    @respx.mock
    async def test_earnings_info(self):
        respx.get("https://financialmodelingprep.com/api/v3/earning_calendar").mock(
            return_value=httpx.Response(200, json=AAPL_EARNINGS_UPCOMING)
        )
        respx.get("https://financialmodelingprep.com/api/v3/historical/earning_calendar/AAPL").mock(
            return_value=httpx.Response(200, json=AAPL_EARNINGS_HISTORICAL)
        )

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_info", {"symbol": "AAPL"})

        data = result.data
        assert data["next_earnings"]["date"] == "2025-04-24"
        assert data["next_earnings"]["eps_estimate"] == 1.62
        assert len(data["earnings_history"]) == 4
        # All 4 quarters should be beats (actual > estimate)
        assert data["surprise_summary"]["beats"] == 4
        assert data["surprise_summary"]["misses"] == 0
        await fmp.close()
