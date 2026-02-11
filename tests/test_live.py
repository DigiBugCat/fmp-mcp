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
from tools.ownership import register as register_ownership
from tools.news import register as register_news
from tools.macro import register as register_macro
from tools.transcripts import register as register_transcripts

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
    register_ownership(mcp, client)
    register_news(mcp, client)
    register_macro(mcp, client)
    register_transcripts(mcp, client)
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


class TestLiveInsiderActivity:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("insider_activity", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        print(f"\n  AAPL insider 30d: {data['net_activity_30d']}")
        print(f"  Cluster buying: {data['cluster_buying']}")
        if data.get("notable_trades"):
            for t in data["notable_trades"][:3]:
                print(f"    {t['name']} ({t['title']}): {t['type']} {t['shares']} @ ${t.get('price', 'N/A')}")
        await client.close()


class TestLiveInstitutionalOwnership:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("institutional_ownership", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        if data.get("top_holders"):
            print(f"\n  Top holders:")
            for h in data["top_holders"][:5]:
                print(f"    {h['holder']}: {h['shares']:,} ({h.get('ownership_pct', 'N/A')}%)")
        print(f"  Position changes: {data.get('position_changes', {})}")
        await client.close()


class TestLiveStockNews:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("stock_news", {"symbol": "AAPL", "limit": 10})
        data = result.data
        assert data["symbol"] == "AAPL"
        assert data["count"] > 0
        print(f"\n  AAPL news: {data['count']} articles")
        for a in data["articles"][:3]:
            flag = f" [{a['event_flag']}]" if a.get("event_flag") else ""
            print(f"    {a['date'][:10]}: {a['title'][:60]}{flag}")
        await client.close()


class TestLiveTreasuryRates:
    @pytest.mark.asyncio
    async def test_treasury(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("treasury_rates", {})
        data = result.data
        assert "yields" in data
        y = data["yields"]
        print(f"\n  Treasury rates ({data.get('date', 'N/A')}):")
        print(f"    2Y={y.get('2y')}, 5Y={y.get('5y')}, 10Y={y.get('10y')}, 30Y={y.get('30y')}")
        print(f"    Slope 10Y-2Y: {data.get('curve_slope_10y_2y')}, Inverted: {data.get('curve_inverted')}")
        dcf = data.get("dcf_inputs", {})
        if dcf.get("implied_cost_of_equity"):
            print(f"    DCF: Rf={dcf['risk_free_rate']}, ERP={dcf['equity_risk_premium']}, CoE={dcf['implied_cost_of_equity']}")
        await client.close()


class TestLiveEconomicCalendar:
    @pytest.mark.asyncio
    async def test_calendar(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("economic_calendar", {"days_ahead": 14})
        data = result.data
        print(f"\n  Economic calendar: {data['count']} high-impact events ({data['period']})")
        for e in data["events"][:5]:
            print(f"    {e['date'][:10]}: {e['event']} (est={e.get('estimate')}, prev={e.get('previous')})")
        await client.close()


class TestLiveMarketOverview:
    @pytest.mark.asyncio
    async def test_overview(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("market_overview", {})
        data = result.data
        if data.get("sectors"):
            print(f"\n  Sector performance:")
            for s in data["sectors"][:5]:
                print(f"    {s['sector']}: {s['change_pct']}%")
        if data.get("top_gainers"):
            print(f"  Top gainers: {', '.join(g['symbol'] for g in data['top_gainers'][:3])}")
        if data.get("top_losers"):
            print(f"  Top losers: {', '.join(l['symbol'] for l in data['top_losers'][:3])}")
        await client.close()


class TestLiveEarningsTranscript:
    @pytest.mark.asyncio
    async def test_aapl_latest(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("earnings_transcript", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        print(f"\n  Transcript: Q{data.get('quarter')} {data.get('year')}, {data.get('length_chars', 0):,} chars")
        if data.get("content"):
            print(f"  Preview: {data['content'][:150]}...")
        await client.close()


class TestLiveRevenueSegments:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("revenue_segments", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        if data.get("product_segments"):
            ps = data["product_segments"]
            print(f"\n  Product segments ({ps.get('date', 'N/A')}):")
            for s in ps.get("segments", [])[:5]:
                growth = f", YoY={s['yoy_growth_pct']}%" if s.get("yoy_growth_pct") is not None else ""
                print(f"    {s['name']}: {s.get('pct_of_total', 0):.1f}%{growth}")
            print(f"  Fastest growing: {ps.get('fastest_growing')}")
            print(f"  Concentration risk: {ps.get('concentration_risk')}")
        if data.get("geographic_segments"):
            gs = data["geographic_segments"]
            print(f"  Geographic segments:")
            for s in gs.get("segments", [])[:5]:
                print(f"    {s['name']}: {s.get('pct_of_total', 0):.1f}%")
        await client.close()


class TestLivePeerComparison:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("peer_comparison", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        print(f"\n  Peers: {data.get('peers', [])[:5]}")
        comps = data.get("comparisons", {})
        if comps.get("pe_ttm"):
            pe = comps["pe_ttm"]
            print(f"  P/E: target={pe['target']}, median={pe['peer_median']}, premium={pe.get('premium_discount_pct')}%, rank={pe.get('rank')}")
        if comps.get("ev_ebitda_ttm"):
            ev = comps["ev_ebitda_ttm"]
            print(f"  EV/EBITDA: target={ev['target']}, median={ev['peer_median']}, premium={ev.get('premium_discount_pct')}%")
        await client.close()


class TestLiveDividendsInfo:
    @pytest.mark.asyncio
    async def test_aapl(self, live_server):
        mcp, client = live_server
        async with Client(mcp) as c:
            result = await c.call_tool("dividends_info", {"symbol": "AAPL"})
        data = result.data
        assert data["symbol"] == "AAPL"
        print(f"\n  AAPL dividends:")
        print(f"    Current yield: {data.get('dividend_yield_pct')}%")
        print(f"    Trailing annual dividend: ${data.get('trailing_annual_dividend')}")
        print(f"    CAGR 3Y: {data.get('dividend_cagr_3y')}%, 5Y: {data.get('dividend_cagr_5y')}%")
        if data.get("upcoming_ex_date"):
            ex = data["upcoming_ex_date"]
            print(f"    Next ex-date: {ex['ex_date']}, ${ex['dividend']}")
        if data.get("stock_splits"):
            splits_str = ", ".join(f"{s['date']}: {s['label']}" for s in data["stock_splits"])
            print(f"    Splits: {splits_str}")
        await client.close()
