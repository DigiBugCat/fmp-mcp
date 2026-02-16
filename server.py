"""Pantainos FMP - Financial data MCP server for investment research."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fmp_data import AsyncFMPDataClient
from fmp_data.config import ClientConfig, RateLimitConfig

from polygon_client import PolygonClient
from tools import assets, economy, edgar, financials, macro, market, meta, news, options, overview, ownership, transcripts, valuation, workflows


@asynccontextmanager
async def lifespan(server):
    """Manage client lifecycles."""
    yield
    await client.aclose()
    if polygon_client is not None:
        await polygon_client.close()


mcp = FastMCP(
    "Pantainos FMP",
    instructions=(
        "Financial data API. Start with workflow tools (stock_brief, market_context, "
        "earnings_setup, earnings_preview, fair_value_estimate, earnings_postmortem, "
        "ownership_deep_dive, industry_analysis) for common questions. "
        "Use atomic tools for targeted queries. All tools are self-documenting. "
        "For 'which funds hold [private company]?' questions (SpaceX, Anthropic, xAI, etc.), "
        "use sec_filings_search with forms='NPORT-P' — this is the only tool that can do "
        "reverse lookups on private company holdings via SEC EDGAR."
    ),
    lifespan=lifespan,
)

# Initialize shared FMP client
api_key = os.environ.get("FMP_API_KEY", "")
if not api_key:
    raise RuntimeError("FMP_API_KEY is required")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


rate_limit_config = RateLimitConfig(
    daily_limit=_env_int("FMP_DAILY_LIMIT", 1_000_000),
    requests_per_second=_env_int("FMP_REQUESTS_PER_SECOND", 30),
    requests_per_minute=_env_int("FMP_REQUESTS_PER_MINUTE", 6_000),
)

client = AsyncFMPDataClient(
    config=ClientConfig(
        api_key=api_key,
        timeout=30,
        max_retries=3,
        rate_limit=rate_limit_config,
    )
)

# Initialize optional Polygon client
polygon_api_key = os.environ.get("POLYGON_API_KEY", "")
polygon_client: PolygonClient | None = None
if polygon_api_key:
    polygon_client = PolygonClient(api_key=polygon_api_key)

# Register tool modules
overview.register(mcp, client)
financials.register(mcp, client)
valuation.register(mcp, client)
market.register(mcp, client, polygon_client=polygon_client)
ownership.register(mcp, client, polygon_client=polygon_client)
news.register(mcp, client)
macro.register(mcp, client)
transcripts.register(mcp, client)
assets.register(mcp, client)
workflows.register(mcp, client)
edgar.register(mcp, client)
meta.register(mcp, client)

# Polygon-only tools (registered only when Polygon key is available)
if polygon_client is not None:
    options.register(mcp, polygon_client)
    economy.register(mcp, polygon_client)
