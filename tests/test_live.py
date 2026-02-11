"""Live integration tests against the real FMP stable API.

Run with: FMP_API_KEY=... uv run pytest tests/test_live.py -v -s
"""

from __future__ import annotations

import os

import pytest

from fastmcp import FastMCP, Client
from fmp_client import FMPClient
from tools.overview import register as register_overview
from tools.financials import register as register_financials
from tools.valuation import register as register_valuation
from tools.market import register as register_market

API_KEY = os.environ.get("FMP_API_KEY", "")
pytestmark = pytest.mark.skipif(not API_KEY, reason="FMP_API_KEY not set")


@pytest.fixture
def live_server():
    mcp = FastMCP("Live Test")
    client = FMPClient(api_key=API_KEY)
    register_overview(mcp, client)
    register_financials(mcp, client)
    register_valuation(mcp, client)
    register_market(mcp, client)
    return mcp, client


class TestLiveCompanyOverview:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["sector"] == "Technology"
        assert data["price"] is not None
        assert data["market_cap"] is not None
        assert data["ratios"]["pe_ttm"] is not None
        print(f"\n  AAPL: ${data['price']}, P/E={data['ratios']['pe_ttm']:.1f}, MCap=${data['market_cap']:,.0f}")
        await client.close()

    @pytest.mark.asyncio
    async def test_msft(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "MSFT"})
        data = result.data
        assert data["symbol"] == "MSFT"
        assert data["price"] is not None
        print(f"\n  MSFT: ${data['price']}, Sector={data['sector']}")
        await client.close()

    @pytest.mark.asyncio
    async def test_invalid_symbol(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("company_overview", {"symbol": "ZZZZZZZZ"})
        data = result.data
        assert "error" in data or data.get("name") is None
        await client.close()


class TestLiveStockSearch:
    @pytest.mark.asyncio
    async def test_search_apple(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("stock_search", {"query": "apple"})
        data = result.data
        assert data["count"] > 0
        print(f"\n  Found {data['count']} results for 'apple'")
        await client.close()

    @pytest.mark.asyncio
    async def test_screener_tech(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("stock_search", {
                "query": "",
                "sector": "Technology",
                "market_cap_min": 100_000_000_000,
                "limit": 10,
            })
        data = result.data
        assert data["count"] > 0
        print(f"\n  Found {data['count']} tech stocks >$100B")
        for r in data["results"][:5]:
            print(f"    {r['symbol']}: {r['name']} MCap=${r.get('market_cap', 0):,.0f}")
        await client.close()


class TestLiveFinancials:
    @pytest.mark.asyncio
    async def test_aapl_annual(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        assert len(data["periods"]) > 0
        p = data["periods"][0]
        assert p["revenue"] is not None
        assert p["gross_margin"] is not None
        print(f"\n  AAPL FY{p['date'][:4]}: Rev=${p['revenue']:,.0f}, GM={p['gross_margin']:.1f}%, NM={p['net_margin']:.1f}%")
        if "growth_3y_cagr" in data:
            g = data["growth_3y_cagr"]
            print(f"  3Y CAGR: Rev={g.get('revenue_cagr_3y')}%, EPS={g.get('eps_cagr_3y')}%")
        await client.close()

    @pytest.mark.asyncio
    async def test_msft_quarterly(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("financial_statements", {"symbol": "MSFT", "period": "quarter", "limit": 4})
        data = result.data
        assert data["period_type"] == "quarter"
        assert len(data["periods"]) > 0
        print(f"\n  MSFT quarterly: {len(data['periods'])} periods")
        await client.close()


class TestLiveAnalystConsensus:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("analyst_consensus", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        pt = data["price_targets"]
        if pt.get("consensus"):
            print(f"\n  AAPL targets: ${pt['consensus']:.0f} (${pt.get('low', 0):.0f}-${pt.get('high', 0):.0f})")
            if pt.get("upside_pct") is not None:
                print(f"  Upside: {pt['upside_pct']:.1f}%")
        grades = data["analyst_grades"]
        if grades.get("buy") is not None:
            print(f"  Grades: StrongBuy={grades.get('strong_buy')}, Buy={grades['buy']}, Hold={grades['hold']}, Sell={grades['sell']}")
        rating = data["fmp_rating"]
        if rating.get("rating"):
            print(f"  FMP Rating: {rating['rating']} (score: {rating['overall_score']})")
        await client.close()


class TestLivePriceHistory:
    @pytest.mark.asyncio
    async def test_aapl_1y(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("price_history", {"symbol": "AAPL"})
        data = result.data
        assert data["current_price"] is not None
        assert data["data_points"] > 200
        print(f"\n  AAPL: ${data['current_price']}, SMA50={data['sma_50']}, SMA200={data['sma_200']}")
        print(f"  52wk: ${data['year_low']}-${data['year_high']}, Vol={data.get('daily_volatility_annualized_pct', 'N/A')}%")
        if data.get("performance_pct"):
            print(f"  Perf: {data['performance_pct']}")
        await client.close()

    @pytest.mark.asyncio
    async def test_tsla_3m(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("price_history", {"symbol": "TSLA", "period": "3m"})
        data = result.data
        assert data["current_price"] is not None
        assert data["data_points"] > 40
        print(f"\n  TSLA 3m: ${data['current_price']}, {data['data_points']} data points")
        await client.close()


class TestLiveEarningsInfo:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_info", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        estimates = data.get("forward_estimates", [])
        quarters = data.get("recent_quarters", [])
        assert len(estimates) > 0 or len(quarters) > 0
        if estimates:
            e = estimates[0]
            print(f"\n  Next estimate: {e['date']}, EPS avg={e['eps_avg']}, analysts={e['num_analysts_eps']}")
        if quarters:
            q = quarters[0]
            print(f"  Latest quarter: {q['date']} ({q['period']}), Rev=${q['revenue']:,.0f}, EPS={q['eps_diluted']}")
        await client.close()
