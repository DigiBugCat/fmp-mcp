"""Tests for workflow tools using respx mocking."""

from __future__ import annotations

import pytest
import respx
import httpx

from fastmcp import FastMCP, Client
from fmp_client import FMPClient
from tests.conftest import (
    AAPL_PROFILE, AAPL_QUOTE, AAPL_RATIOS,
    AAPL_INCOME, AAPL_BALANCE, AAPL_CASHFLOW,
    AAPL_PRICE_TARGET, AAPL_GRADES, AAPL_HISTORICAL,
    AAPL_ANALYST_ESTIMATES, AAPL_QUARTERLY_INCOME,
    AAPL_INSIDER_TRADES, AAPL_INSIDER_STATS, AAPL_SHARES_FLOAT,
    AAPL_NEWS, AAPL_KEY_METRICS,
    AAPL_PEERS, AAPL_EARNINGS, AAPL_GRADES_DETAIL,
    AAPL_TRANSCRIPT_DATES, AAPL_TRANSCRIPT,
    TREASURY_RATES, MARKET_RISK_PREMIUM, ECONOMIC_CALENDAR,
    SECTOR_PERFORMANCE, BIGGEST_GAINERS, BIGGEST_LOSERS, MOST_ACTIVES,
    MSFT_RATIOS, MSFT_KEY_METRICS,
    GOOGL_RATIOS, GOOGL_KEY_METRICS,
    AMZN_RATIOS, AMZN_KEY_METRICS,
)
from tools.workflows import register as register_workflows

BASE = "https://financialmodelingprep.com"


def _make_server() -> tuple[FastMCP, FMPClient]:
    mcp = FastMCP("Test")
    client = FMPClient(api_key="test_key")
    register_workflows(mcp, client)
    return mcp, client


# ================================================================
# stock_brief
# ================================================================


class TestStockBrief:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_brief(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=AAPL_RATIOS))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=AAPL_HISTORICAL))
        respx.get(f"{BASE}/stable/grades-consensus").mock(return_value=httpx.Response(200, json=AAPL_GRADES))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=AAPL_PRICE_TARGET))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_TRADES))
        respx.get(f"{BASE}/stable/news/stock").mock(return_value=httpx.Response(200, json=AAPL_NEWS))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("stock_brief", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["company_name"] == "Apple Inc."
        assert data["price"]["current"] == 273.68
        assert data["valuation"]["pe"] == 34.27
        assert data["analyst"]["consensus"] == "Buy"
        assert data["analyst"]["target"] == 303.11
        assert data["analyst"]["upside_pct"] is not None
        assert isinstance(data["news"], list)
        assert len(data["news"]) <= 5
        assert data["quick_take"]["signal"] in ("bullish", "neutral", "bearish")
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_brief(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/grades-consensus").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/news/stock").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("stock_brief", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["company_name"] == "Apple Inc."
        assert "ratios unavailable" in data["_warnings"]
        assert "historical prices unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/grades-consensus").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/news/stock").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("stock_brief", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


# ================================================================
# market_context
# ================================================================


class TestMarketContext:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_context(self):
        respx.get(f"{BASE}/stable/treasury-rates").mock(return_value=httpx.Response(200, json=TREASURY_RATES))
        respx.get(f"{BASE}/stable/market-risk-premium").mock(return_value=httpx.Response(200, json=MARKET_RISK_PREMIUM))
        respx.get(f"{BASE}/stable/economic-calendar").mock(return_value=httpx.Response(200, json=ECONOMIC_CALENDAR))
        respx.get(f"{BASE}/stable/sector-performance-snapshot").mock(return_value=httpx.Response(200, json=SECTOR_PERFORMANCE))
        respx.get(f"{BASE}/stable/biggest-gainers").mock(return_value=httpx.Response(200, json=BIGGEST_GAINERS))
        respx.get(f"{BASE}/stable/biggest-losers").mock(return_value=httpx.Response(200, json=BIGGEST_LOSERS))
        respx.get(f"{BASE}/stable/most-actives").mock(return_value=httpx.Response(200, json=MOST_ACTIVES))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("market_context", {})

        data = result.data
        assert data["rates"]["10y"] == 4.05
        assert data["rates"]["2y"] == 3.82
        assert data["rates"]["spread_bps"] == 23
        assert data["rates"]["inverted"] is False
        assert data["rates"]["erp"] == 4.60
        assert data["rates"]["cost_of_equity"] == 8.65
        assert len(data["rotation"]["leaders"]) > 0
        assert data["rotation"]["signal"] in ("risk_on", "risk_off", "mixed")
        assert data["breadth"]["signal"] in ("bullish", "bearish", "neutral")
        assert data["environment"]["regime"] in ("risk_on", "risk_off", "neutral")
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_context(self):
        respx.get(f"{BASE}/stable/treasury-rates").mock(return_value=httpx.Response(200, json=TREASURY_RATES))
        respx.get(f"{BASE}/stable/market-risk-premium").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/economic-calendar").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/sector-performance-snapshot").mock(return_value=httpx.Response(200, json=SECTOR_PERFORMANCE))
        respx.get(f"{BASE}/stable/biggest-gainers").mock(return_value=httpx.Response(200, json=BIGGEST_GAINERS))
        respx.get(f"{BASE}/stable/biggest-losers").mock(return_value=httpx.Response(200, json=BIGGEST_LOSERS))
        respx.get(f"{BASE}/stable/most-actives").mock(return_value=httpx.Response(200, json=MOST_ACTIVES))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("market_context", {})

        data = result.data
        assert data["rates"]["10y"] == 4.05
        assert data["rates"]["erp"] is None
        assert "risk premium unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_context(self):
        respx.get(f"{BASE}/stable/treasury-rates").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/market-risk-premium").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/economic-calendar").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/sector-performance-snapshot").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/biggest-gainers").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/biggest-losers").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/most-actives").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("market_context", {})

        data = result.data
        assert "error" in data
        await fmp.close()


# ================================================================
# earnings_setup
# ================================================================


class TestEarningsSetup:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_setup(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=AAPL_EARNINGS))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(200, json=AAPL_GRADES_DETAIL))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=AAPL_HISTORICAL))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_TRADES))
        respx.get(f"{BASE}/stable/insider-trading/statistics").mock(return_value=httpx.Response(200, json=AAPL_INSIDER_STATS))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=AAPL_SHARES_FLOAT))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_setup", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["company_name"] == "Apple Inc."
        assert data["current_price"] == 273.68
        # Next earnings date should exist
        assert data["earnings_date"] is not None
        assert data["days_until_earnings"] is not None
        # Consensus
        assert data["consensus"]["eps"] is not None
        # Surprise history
        assert data["surprise_history"]["beat_rate"] is not None
        assert data["surprise_history"]["beat_rate"] > 0
        assert len(data["surprise_history"]["last_quarters"]) > 0
        # Analyst momentum
        assert data["analyst_momentum"]["signal"] in ("positive", "negative", "neutral")
        # Setup summary
        assert data["setup_summary"]["signal"] in ("bullish", "neutral", "bearish")
        assert isinstance(data["setup_summary"]["key_factors"], list)
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_setup(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=AAPL_PROFILE))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=AAPL_EARNINGS))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/insider-trading/statistics").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(500, text="error"))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_setup", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["surprise_history"]["beat_rate"] is not None  # earnings data still works
        assert "analyst grades unavailable" in data["_warnings"]
        assert "historical prices unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/profile").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/insider-trading/search").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/insider-trading/statistics").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/shares-float").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_setup", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


# ================================================================
# fair_value_estimate
# ================================================================


class TestFairValueEstimate:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_valuation(self):
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=AAPL_INCOME))
        respx.get(f"{BASE}/stable/balance-sheet-statement").mock(return_value=httpx.Response(200, json=AAPL_BALANCE))
        respx.get(f"{BASE}/stable/cash-flow-statement").mock(return_value=httpx.Response(200, json=AAPL_CASHFLOW))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "AAPL"}).mock(return_value=httpx.Response(200, json=AAPL_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "AAPL"}).mock(return_value=httpx.Response(200, json=AAPL_RATIOS))
        respx.get(f"{BASE}/stable/analyst-estimates").mock(return_value=httpx.Response(200, json=AAPL_ANALYST_ESTIMATES))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=AAPL_PRICE_TARGET))
        respx.get(f"{BASE}/stable/stock-peers").mock(return_value=httpx.Response(200, json=AAPL_PEERS))
        # Peer data
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "MSFT"}).mock(return_value=httpx.Response(200, json=MSFT_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "MSFT"}).mock(return_value=httpx.Response(200, json=MSFT_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "GOOGL"}).mock(return_value=httpx.Response(200, json=GOOGL_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "GOOGL"}).mock(return_value=httpx.Response(200, json=GOOGL_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm", params__contains={"symbol": "AMZN"}).mock(return_value=httpx.Response(200, json=AMZN_RATIOS))
        respx.get(f"{BASE}/stable/key-metrics-ttm", params__contains={"symbol": "AMZN"}).mock(return_value=httpx.Response(200, json=AMZN_KEY_METRICS))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("fair_value_estimate", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["current_price"] == 273.68
        # Fundamentals
        assert data["fundamentals"]["market_cap"] is not None
        assert data["fundamentals"]["ttm_revenue"] is not None
        assert data["fundamentals"]["ttm_fcf"] is not None
        # Multiples
        assert data["multiples"]["current"]["pe"] == 34.27
        assert data["multiples"]["peer_median"]["pe"] is not None
        assert data["multiples"]["premium_pct"]["pe"] is not None
        # Fair value methods
        fv = data["fair_value"]
        assert fv["analyst_target"] == 303.11
        assert fv["blended"] is not None
        assert fv["upside_pct"] is not None
        # Summary
        assert data["summary"]["rating"] in ("undervalued", "overvalued", "fairly_valued", "insufficient_data")
        assert data["summary"]["confidence"] in ("high", "medium", "low")
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_peers(self):
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=AAPL_INCOME))
        respx.get(f"{BASE}/stable/balance-sheet-statement").mock(return_value=httpx.Response(200, json=AAPL_BALANCE))
        respx.get(f"{BASE}/stable/cash-flow-statement").mock(return_value=httpx.Response(200, json=AAPL_CASHFLOW))
        respx.get(f"{BASE}/stable/key-metrics-ttm").mock(return_value=httpx.Response(200, json=AAPL_KEY_METRICS))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=AAPL_RATIOS))
        respx.get(f"{BASE}/stable/analyst-estimates").mock(return_value=httpx.Response(200, json=AAPL_ANALYST_ESTIMATES))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=AAPL_PRICE_TARGET))
        respx.get(f"{BASE}/stable/stock-peers").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("fair_value_estimate", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        # Should still have analyst target even without peers
        assert data["fair_value"]["analyst_target"] == 303.11
        assert "peer data unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_symbol(self):
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/balance-sheet-statement").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/cash-flow-statement").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/key-metrics-ttm").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/ratios-ttm").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/analyst-estimates").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/stock-peers").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("fair_value_estimate", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()


# ================================================================
# earnings_postmortem
# ================================================================


class TestEarningsPostmortem:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_postmortem(self):
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=AAPL_EARNINGS))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=AAPL_QUARTERLY_INCOME))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(200, json=AAPL_GRADES_DETAIL))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=AAPL_PRICE_TARGET))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=AAPL_HISTORICAL))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/earning-call-transcript-dates").mock(return_value=httpx.Response(200, json=AAPL_TRANSCRIPT_DATES))
        # The transcript fetch may or may not happen depending on date matching
        respx.get(f"{BASE}/stable/earning-call-transcript").mock(return_value=httpx.Response(200, json=AAPL_TRANSCRIPT))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_postmortem", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["earnings_date"] is not None
        # Results
        assert data["results"]["actual_eps"] is not None
        assert data["results"]["est_eps"] is not None
        assert data["results"]["surprise_pct"] is not None
        assert data["results"]["beat"] is True  # AAPL mock data beats estimates
        # Summary
        assert "beat" in data["summary"]["headline"].lower() or "miss" in data["summary"]["headline"].lower() or "results" in data["summary"]["headline"].lower()
        assert isinstance(data["summary"]["key_positives"], list)
        assert isinstance(data["summary"]["key_concerns"], list)
        assert "_warnings" not in data
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_partial_postmortem(self):
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=AAPL_EARNINGS))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(500, text="error"))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=AAPL_QUOTE))
        respx.get(f"{BASE}/stable/earning-call-transcript-dates").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/earning-call-transcript").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_postmortem", {"symbol": "AAPL"})

        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["results"]["beat"] is True  # earnings data still works
        assert "income statement unavailable" in data["_warnings"]
        assert "analyst grades unavailable" in data["_warnings"]
        await fmp.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_earnings(self):
        respx.get(f"{BASE}/stable/earnings").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/income-statement").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/grades").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/price-target-consensus").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/historical-price-eod/full").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/quote").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{BASE}/stable/earning-call-transcript-dates").mock(return_value=httpx.Response(200, json=[]))

        mcp, fmp = _make_server()
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_postmortem", {"symbol": "ZZZZ"})

        data = result.data
        assert "error" in data
        await fmp.close()
