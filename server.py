"""Pantainos FMP - Financial data MCP server for investment research."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from fmp_client import FMPClient
from tools import financials, macro, market, news, overview, ownership, transcripts, valuation


@asynccontextmanager
async def lifespan(server):
    """Manage FMPClient lifecycle."""
    yield
    await client.close()


mcp = FastMCP(
    "Pantainos FMP",
    instructions=(
        "Financial data server for investment research. "
        "Start with company_overview for any stock query, then drill deeper "
        "with financial_statements, analyst_consensus, earnings_info, or price_history. "
        "Use stock_search to discover tickers. "
        "For ownership signals use insider_activity and institutional_ownership. "
        "For news use stock_news. For macro context use treasury_rates, economic_calendar, "
        "or market_overview. Use earnings_transcript for call transcripts, "
        "revenue_segments for business mix, peer_comparison for relative valuation, "
        "and dividends_info for dividend analysis."
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
