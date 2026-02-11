"""Tests for FMP MCP server tools using respx mocking."""

from __future__ import annotations

import pytest
import respx
import httpx

from fastmcp import FastMCP, Client
from fmp_client import FMPClient, FMPError
from tests.conftest import (
    AAPL_PROFILE, AAPL_QUOTE, AAPL_RATIOS,
    AAPL_INCOME, AAPL_BALANCE, AAPL_CASHFLOW,
    AAPL_PRICE_TARGET, AAPL_GRADES, AAPL_RATING,
    AAPL_SEARCH, AAPL_SCREENER, AAPL_HISTORICAL,
    AAPL_ANALYST_ESTIMATES, AAPL_QUARTERLY_INCOME,
)
from tools.overview import register as register_overview
from tools.financials import register as register_financials
from tools.valuation import register as register_valuation
from tools.market import register as register_market

BASE = "https://financialmodelingprep.com"


# --- FMPClient Tests ---


class TestFMPClient:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_api, fmp_client):
        mock_api.get("/stable/profile").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        result = await fmp_client.get("/stable/profile", params={"symbol": "AAPL"})
        assert result[0]["companyName"] == "Apple Inc."

    @pytest.mark.asyncio
    async def test_get_caching(self, mock_api, fmp_client):
        route = mock_api.get("/stable/profile").mock(
            return_value=httpx.Response(200, json=AAPL_PROFILE)
        )
        await fmp_client.get("/stable/profile", params={"symbol": "AAPL"}, cache_ttl=300)
        await fmp_client.get("/stable/profile", params={"symbol": "AAPL"}, cache_ttl=300)
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_get_error_message(self, mock_api, fmp_client):
        mock_api.get("/stable/profile").mock(
            return_value=httpx.Response(200, json={"Error Message": "Invalid API KEY."})
        )
        with pytest.raises(FMPError, match="Invalid API KEY"):
            await fmp_client.get("/stable/profile", params={"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_get_http_error(self, mock_api, fmp_client):
        mock_api.get("/stable/profile").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        with pytest.raises(FMPError, match="429"):
            await fmp_client.get("/stable/profile")

    @pytest.mark.asyncio
    async def test_get_safe_returns_default(self, mock_api, fmp_client):
        mock_api.get("/stable/profile").mock(
            return_value=httpx.Response(404, text="Not found")
        )
        result = await fmp_client.get_safe("/stable/profile", default=[])
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
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=AAPL_RATIOS))

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["price"] == 273.68
        assert data["ratios"]["pe_ttm"] == 34.27
        assert data["sma_50"] == 268.66
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_data(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(500, text="error"))

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
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestStockSearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_name_search(self):
        respx.get(f"{BASE}/stable/search-name").mock(return_value=httpx.Response(200, json=AAPL_SEARCH))

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_search", {"query": "apple"})

        data = result.data
        assert data["count"] == 2
        assert data["results"][0]["symbol"] == "APC.F"
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_screener_search(self):
        respx.get(f"{BASE}/stable/company-screener").mock(return_value=httpx.Response(200, json=AAPL_SCREENER))

        mcp, fmp = _make_server(register_overview)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_search", {
                "query": "",
                "sector": "Technology",
                "market_cap_min": 100000000000,
            })

        data = result.data
        assert data["count"] == 2
        assert data["results"][0]["symbol"] == "NVDA"
        await fmp.close()


class TestFinancialStatements:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_financials(self):
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=AAPL_INCOME))
        respx.get(f"{BASE}/stable/balance-sheet-statement").mock(return_value=httpx.Response(200, json=AAPL_BALANCE))
        respx.get(f"{BASE}/stable/cash-flow-statement").mock(return_value=httpx.Response(200, json=AAPL_CASHFLOW))

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["periods"]) == 4
        assert data["periods"][0]["revenue"] == 416161000000
        assert data["periods"][0]["free_cash_flow"] == 98767000000
        assert "growth_3y_cagr" in data
        assert data["growth_3y_cagr"]["revenue_cagr_3y"] is not None
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_margins_calculated(self):
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=AAPL_INCOME))
        respx.get(f"{BASE}/stable/balance-sheet-statement").mock(return_value=httpx.Response(200, json=AAPL_BALANCE))
        respx.get(f"{BASE}/stable/cash-flow-statement").mock(return_value=httpx.Response(200, json=AAPL_CASHFLOW))

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "AAPL"})

        data = result.data
        p = data["periods"][0]
        assert p["gross_margin"] is not None
        assert p["gross_margin"] > 40
        await fmp.close()


class TestAnalystConsensus:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_consensus(self):
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=AAPL_PRICE_TARGET))
        respx.get(f"{BASE}/stable/grades-consensus").mock(return_value=httpx.Response(200, json=AAPL_GRADES))
        respx.get(f"{BASE}/stable/ratings-snapshot").mock(return_value=httpx.Response(200, json=AAPL_RATING))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))

        mcp, fmp = _make_server(register_valuation)
        async with Client(mcp) as c:
            result = await c.call_tool("analyst_consensus", {"symbol": "AAPL"})

        data = result.data
        assert data["price_targets"]["consensus"] == 303.11
        assert data["price_targets"]["upside_pct"] is not None
        assert data["analyst_grades"]["buy"] == 68
        assert data["analyst_grades"]["strong_buy"] == 1
        assert data["fmp_rating"]["rating"] == "B"
        assert data["fmp_rating"]["overall_score"] == 3
        await fmp.close()


class TestPriceHistory:
    @pytest.mark.asyncio
    @respx.mock
    async def test_price_history(self):
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=AAPL_HISTORICAL))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("price_history", {"symbol": "AAPL"})

        data = result.data
        assert data["current_price"] == 273.68
        assert data["year_high"] == 288.62
        assert data["sma_50"] == 268.66
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
        respx.get(f"{BASE}/stable/analyst-estimates").mock(
            return_value=httpx.Response(200, json=AAPL_ANALYST_ESTIMATES)
        )
        respx.get(f"{BASE}/stable/income-statement").mock(
            return_value=httpx.Response(200, json=AAPL_QUARTERLY_INCOME)
        )

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_info", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["forward_estimates"]) == 3
        assert data["forward_estimates"][0]["eps_avg"] is not None
        assert data["forward_estimates"][0]["num_analysts_eps"] is not None
        assert len(data["recent_quarters"]) == 4
        assert data["recent_quarters"][0]["eps_diluted"] == 2.40
        await fmp.close()
