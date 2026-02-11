"""Pantainos FMP - Financial data MCP server for investment research."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from fmp_client import FMPClient
from tools import assets, financials, macro, market, meta, news, overview, ownership, transcripts, valuation, workflows


@asynccontextmanager
async def lifespan(server):
    """Manage FMPClient lifecycle."""
    yield
    await client.close()


mcp = FastMCP(
    "Pantainos FMP",
    instructions=(
        "Financial data server for investment research. "
        "WORKFLOW TOOLS (start here for common questions): "
        "stock_brief for a quick comprehensive read on any stock, "
        "market_context for macro + rotation + breadth environment, "
        "earnings_setup for pre-earnings positioning analysis, "
        "fair_value_estimate for multi-method valuation, "
        "earnings_postmortem for post-earnings synthesis, "
        "ownership_deep_dive for comprehensive ownership analysis. "
        "ATOMIC TOOLS (for deeper dives): "
        "company_overview, financial_statements, analyst_consensus, "
        "earnings_info, price_history, intraday_prices, stock_search, "
        "insider_activity, institutional_ownership, short_interest, "
        "fund_holdings, ownership_structure, market_news, treasury_rates, "
        "economic_calendar, market_overview, index_performance, "
        "market_hours, industry_performance, earnings_transcript, "
        "revenue_segments, peer_comparison, dividends_info, "
        "earnings_calendar, etf_lookup, estimate_revisions, "
        "company_executives, sec_filings, technical_indicators, "
        "financial_health, ipo_calendar, splits_calendar, "
        "dividends_calendar, index_constituents, sector_valuation, "
        "historical_market_cap, mna_activity, commodity_quotes, "
        "crypto_quotes, forex_quotes, valuation_history, ratio_history, "
        "fmp_coverage_gaps."
    ),
    lifespan=lifespan,
)

# Initialize shared client
api_key = os.environ.get("FMP_API_KEY", "")
if not api_key:
    import warnings
    warnings.warn("FMP_API_KEY not set - API calls will fail", stacklevel=1)

client = FMPClient(api_key=api_key)

# Register tool modules
overview.register(mcp, client)
financials.register(mcp, client)
valuation.register(mcp, client)
market.register(mcp, client)
ownership.register(mcp, client)
news.register(mcp, client)
macro.register(mcp, client)
transcripts.register(mcp, client)
assets.register(mcp, client)
workflows.register(mcp, client)
meta.register(mcp, client)
