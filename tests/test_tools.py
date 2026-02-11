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
    AAPL_INSIDER_TRADES, AAPL_INSIDER_STATS, AAPL_SHARES_FLOAT,
    AAPL_INSTITUTIONAL_SUMMARY, AAPL_INSTITUTIONAL_HOLDERS,
    AAPL_NEWS, AAPL_PRESS_RELEASES,
    TREASURY_RATES, MARKET_RISK_PREMIUM, ECONOMIC_CALENDAR,
    SECTOR_PERFORMANCE, BIGGEST_GAINERS, BIGGEST_LOSERS, MOST_ACTIVES,
    AAPL_TRANSCRIPT_DATES, AAPL_TRANSCRIPT,
    AAPL_PRODUCT_SEGMENTS, AAPL_GEO_SEGMENTS,
    AAPL_PEERS, AAPL_KEY_METRICS,
    MSFT_RATIOS, MSFT_KEY_METRICS,
    GOOGL_RATIOS, GOOGL_KEY_METRICS,
    AMZN_RATIOS, AMZN_KEY_METRICS,
    AAPL_DIVIDENDS, AAPL_STOCK_SPLITS,
)
from tools.overview import register as register_overview
from tools.financials import register as register_financials
from tools.valuation import register as register_valuation
from tools.market import register as register_market
from tools.ownership import register as register_ownership
from tools.news import register as register_news
from tools.macro import register as register_macro
from tools.transcripts import register as register_transcripts

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


# --- New Tool Tests (Tier 1: Unblock Broken Agents) ---


class TestInsiderActivity:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_insider_data(self):
        respx.get(f"{BASE}/stable/insider-trading").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_TRADES))
        respx.get(f"{BASE}/stable/insider-trading-statistics").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_STATS))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=AAPL_SHARES_FLOAT))

        mcp, fmp = _make_server(register_ownership)
        async with Client(mcp) as c:
            result = await c.call_tool("insider_activity", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["statistics"]["total_bought"] == 23000
        assert data["statistics"]["total_sold"] == 70000
        assert data["float_context"]["float_shares"] == 14700000000
        assert len(data["notable_trades"]) > 0
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_data(self):
        respx.get(f"{BASE}/stable/insider-trading").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_TRADES))
        respx.get(f"{BASE}/stable/insider-trading-statistics").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_ownership)
        async with Client(mcp) as c:
            result = await c.call_tool("insider_activity", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert "insider statistics unavailable" in data["_warnings"]
        assert "float data unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/insider-trading").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/insider-trading-statistics").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_ownership)
        async with Client(mcp) as c:
            result = await c.call_tool("insider_activity", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestInstitutionalOwnership:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_institutional(self):
        respx.get(f"{BASE}/stable/institutional-ownership-positions-summary").mock(return_value=httpx.Response(200, json=AAPL_INSTITUTIONAL_SUMMARY))
        respx.get(f"{BASE}/stable/institutional-ownership").mock(return_value=httpx.Response(200, json=AAPL_INSTITUTIONAL_HOLDERS))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=AAPL_SHARES_FLOAT))

        mcp, fmp = _make_server(register_ownership)
        async with Client(mcp) as c:
            result = await c.call_tool("institutional_ownership", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["top_holders"]) == 5
        assert data["top_holders"][0]["holder"] == "Vanguard Group"
        assert data["position_changes"]["increased"] == 1200
        assert data["ownership_summary"]["institutional_pct_of_float"] is not None
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/institutional-ownership-positions-summary").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/institutional-ownership").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_ownership)
        async with Client(mcp) as c:
            result = await c.call_tool("institutional_ownership", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestStockNews:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_news(self):
        respx.get(f"{BASE}/stable/stock-news").mock(return_value=httpx.Response(200, json=AAPL_NEWS))
        respx.get(f"{BASE}/stable/press-releases").mock(return_value=httpx.Response(200, json=AAPL_PRESS_RELEASES))

        mcp, fmp = _make_server(register_news)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_news", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["count"] > 0
        # Dedup should remove the duplicate "Record Q1 Earnings" title
        titles = [a["title"] for a in data["articles"]]
        assert titles.count("Apple Reports Record Q1 Earnings") == 1
        # Check event flags
        earnings_articles = [a for a in data["articles"] if a.get("event_flag") == "earnings"]
        assert len(earnings_articles) > 0
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_news_only(self):
        respx.get(f"{BASE}/stable/stock-news").mock(return_value=httpx.Response(200, json=AAPL_NEWS))
        respx.get(f"{BASE}/stable/press-releases").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_news)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_news", {"symbol": "AAPL"})

        data = result.data
        assert data["count"] == 3
        assert "press releases unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/stock-news").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/press-releases").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_news)
        async with Client(mcp) as c:
            result = await c.call_tool("stock_news", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestTreasuryRates:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_treasury(self):
        respx.get(f"{BASE}/stable/treasury-rates").mock(return_value=httpx.Response(200, json=TREASURY_RATES))
        respx.get(f"{BASE}/stable/market-risk-premium").mock(return_value=httpx.Response(200, json=MARKET_RISK_PREMIUM))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("treasury_rates", {})

        data = result.data
        assert data["date"] == "2026-02-10"
        assert data["yields"]["10y"] == 4.05
        assert data["yields"]["2y"] == 3.82
        assert data["curve_slope_10y_2y"] == 0.23
        assert data["curve_inverted"] is False
        assert data["dcf_inputs"]["risk_free_rate"] == 4.05
        assert data["dcf_inputs"]["equity_risk_premium"] == 4.60
        assert data["dcf_inputs"]["implied_cost_of_equity"] == 8.65
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_erp(self):
        respx.get(f"{BASE}/stable/treasury-rates").mock(return_value=httpx.Response(200, json=TREASURY_RATES))
        respx.get(f"{BASE}/stable/market-risk-premium").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("treasury_rates", {})

        data = result.data
        assert data["yields"]["10y"] == 4.05
        assert data["dcf_inputs"]["equity_risk_premium"] is None
        assert "equity risk premium unavailable" in data["_warnings"]
        await fmp.close()


class TestEconomicCalendar:
    @pytest.mark.asyncio
    @respx.mock
    async def test_filtered_events(self):
        respx.get(f"{BASE}/stable/economic-calendar").mock(return_value=httpx.Response(200, json=ECONOMIC_CALENDAR))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("economic_calendar", {"days_ahead": 7})

        data = result.data
        assert data["count"] > 0
        # ECB event should be filtered out (non-US)
        events = data["events"]
        countries = set()
        for e in events:
            # All events should be US (non-US filtered)
            assert "ECB" not in (e.get("event") or "")
        # CPI and Retail Sales should be present
        event_names = [e["event"] for e in events]
        assert any("CPI" in n for n in event_names)
        assert any("Retail Sales" in n for n in event_names)
        # Business Inventories should be filtered out (not high-impact keyword)
        assert not any("Business Inventories" in n for n in event_names)
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_calendar(self):
        respx.get(f"{BASE}/stable/economic-calendar").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("economic_calendar", {})

        data = result.data
        assert data["count"] == 0
        assert data["events"] == []
        await fmp.close()


class TestMarketOverview:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_market_overview(self):
        respx.get(f"{BASE}/stable/sector-performance-snapshot").mock(return_value=httpx.Response(200, json=SECTOR_PERFORMANCE))
        respx.get(f"{BASE}/stable/biggest-gainers").mock(return_value=httpx.Response(200, json=BIGGEST_GAINERS))
        respx.get(f"{BASE}/stable/biggest-losers").mock(return_value=httpx.Response(200, json=BIGGEST_LOSERS))
        respx.get(f"{BASE}/stable/most-actives").mock(return_value=httpx.Response(200, json=MOST_ACTIVES))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("market_overview", {})

        data = result.data
        assert len(data["sectors"]) == 4
        assert data["sectors"][0]["sector"] == "Technology"  # Highest change
        assert len(data["top_gainers"]) == 2
        assert data["top_gainers"][0]["symbol"] == "XYZ"
        assert len(data["top_losers"]) == 2
        assert len(data["most_active"]) == 2
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_market(self):
        respx.get(f"{BASE}/stable/sector-performance-snapshot").mock(return_value=httpx.Response(200, json=SECTOR_PERFORMANCE))
        respx.get(f"{BASE}/stable/biggest-gainers").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/biggest-losers").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/most-actives").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_macro)
        async with Client(mcp) as c:
            result = await c.call_tool("market_overview", {})

        data = result.data
        assert len(data["sectors"]) == 4
        assert "gainers data unavailable" in data["_warnings"]
        await fmp.close()


# --- New Tool Tests (Tier 2: Research Power-Ups) ---


class TestEarningsTranscript:
    @pytest.mark.asyncio
    @respx.mock
    async def test_latest_transcript(self):
        respx.get(f"{BASE}/stable/earning-call-transcript-dates").mock(return_value=httpx.Response(200, json=AAPL_TRANSCRIPT_DATES))
        respx.get(f"{BASE}/stable/earning-call-transcript").mock(return_value=httpx.Response(200, json=AAPL_TRANSCRIPT))

        mcp, fmp = _make_server(register_transcripts)
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_transcript", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["year"] == 2025
        assert data["quarter"] == 4
        assert "Tim Cook" in data["content"]
        assert data["length_chars"] > 0
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_specific_quarter(self):
        respx.get(f"{BASE}/stable/earning-call-transcript").mock(return_value=httpx.Response(200, json=AAPL_TRANSCRIPT))

        mcp, fmp = _make_server(register_transcripts)
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_transcript", {"symbol": "AAPL", "year": 2025, "quarter": 4})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["quarter"] == 4
        assert data["year"] == 2025
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_transcripts(self):
        respx.get(f"{BASE}/stable/earning-call-transcript-dates").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_transcripts)
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_transcript", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestRevenueSegments:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_segments(self):
        respx.get(f"{BASE}/stable/revenue-product-segmentation").mock(return_value=httpx.Response(200, json=AAPL_PRODUCT_SEGMENTS))
        respx.get(f"{BASE}/stable/revenue-geographic-segmentation").mock(return_value=httpx.Response(200, json=AAPL_GEO_SEGMENTS))

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("revenue_segments", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert "product_segments" in data
        assert "geographic_segments" in data
        # Product segments should be sorted by revenue desc
        products = data["product_segments"]["segments"]
        assert products[0]["name"] == "iPhone"
        assert products[0]["pct_of_total"] is not None
        # iPhone should have concentration risk (>50%? Let's check)
        assert data["product_segments"]["concentration_risk"] is not None
        # Geographic segments
        geos = data["geographic_segments"]["segments"]
        assert geos[0]["name"] == "Americas"
        # YoY growth should be calculated
        assert products[0].get("yoy_growth_pct") is not None
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_product_only(self):
        respx.get(f"{BASE}/stable/revenue-product-segmentation").mock(return_value=httpx.Response(200, json=AAPL_PRODUCT_SEGMENTS))
        respx.get(f"{BASE}/stable/revenue-geographic-segmentation").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("revenue_segments", {"symbol": "AAPL"})

        data = result.data
        assert "product_segments" in data
        assert "geographic_segments" not in data
        assert "geographic segmentation unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/revenue-product-segmentation").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/revenue-geographic-segmentation").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_financials)
        async with Client(mcp) as c:
            result = await c.call_tool("revenue_segments", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestPeerComparison:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_peer_comparison(self):
        respx.get(f"{BASE}/stable/company-peer").mock(return_value=httpx.Response(200, json=AAPL_PEERS))
        # Target (AAPL) ratios & metrics
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "AAPL"}).mock(return_value=httpx.Response(200, json=AAPL_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "AAPL"}).mock(return_value=httpx.Response(200, json=AAPL_KEY_METRICS))
        # Peer ratios & metrics
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "MSFT"}).mock(return_value=httpx.Response(200, json=MSFT_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "MSFT"}).mock(return_value=httpx.Response(200, json=MSFT_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "GOOGL"}).mock(return_value=httpx.Response(200, json=GOOGL_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "GOOGL"}).mock(return_value=httpx.Response(200, json=GOOGL_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "AMZN"}).mock(return_value=httpx.Response(200, json=AMZN_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "AMZN"}).mock(return_value=httpx.Response(200, json=AMZN_KEY_METRICS))

        mcp, fmp = _make_server(register_valuation)
        async with Client(mcp) as c:
            result = await c.call_tool("peer_comparison", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["peers"] == ["MSFT", "GOOGL", "AMZN"]
        assert data["peer_count"] == 3
        # Check comparisons structure
        pe_comp = data["comparisons"]["pe_ttm"]
        assert pe_comp["target"] == 34.27
        assert pe_comp["peer_median"] is not None
        assert pe_comp["premium_discount_pct"] is not None
        assert pe_comp["rank"] is not None
        assert len(data["peer_details"]) == 3
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_peers(self):
        respx.get(f"{BASE}/stable/company-peer").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server(register_valuation)
        async with Client(mcp) as c:
            result = await c.call_tool("peer_comparison", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


class TestDividendsInfo:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_dividends(self):
        respx.get(f"{BASE}/stable/dividends").mock(return_value=httpx.Response(200, json=AAPL_DIVIDENDS))
        respx.get(f"{BASE}/stable/stock-splits").mock(return_value=httpx.Response(200, json=AAPL_STOCK_SPLITS))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("dividends_info", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["current_price"] == 273.68
        assert data["current_annual_dividend"] is not None
        assert data["dividend_yield_pct"] is not None
        assert data["dividend_yield_pct"] > 0
        assert len(data["recent_dividends"]) == 8
        assert len(data["stock_splits"]) == 2
        assert data["stock_splits"][0]["label"] == "4:1"
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_dividends(self):
        respx.get(f"{BASE}/stable/dividends").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/stock-splits").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("dividends_info", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_dividends_partial(self):
        respx.get(f"{BASE}/stable/dividends").mock(return_value=httpx.Response(200, json=AAPL_DIVIDENDS))
        respx.get(f"{BASE}/stable/stock-splits").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server(register_market)
        async with Client(mcp) as c:
            result = await c.call_tool("dividends_info", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["recent_dividends"]) > 0
        assert "stock split data unavailable" in data["_warnings"]
        assert "quote data unavailable" in data["_warnings"]
        await fmp.close()
