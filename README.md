# FMP MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that provides financial data from [Financial Modeling Prep](https://financialmodelingprep.com/) for AI-assisted investment research.

Built with [FastMCP 2.0](https://github.com/jlowin/fastmcp) and Python.

## Tools

### Workflow Tools (start here)

High-level tools that orchestrate multiple API calls into single research-ready responses:

| Tool | Description |
|------|-------------|
| `stock_brief` | Quick comprehensive snapshot: profile, price action, valuation, analyst consensus, insider signals, headlines |
| `market_context` | Full market environment: rates, yield curve, sector rotation, breadth, movers, economic calendar |
| `earnings_setup` | Pre-earnings positioning: consensus estimates, beat/miss history, analyst momentum, price drift, insider signals |
| `fair_value_estimate` | Multi-method valuation: DCF, earnings-based, peer multiples, analyst targets, blended estimate |
| `earnings_postmortem` | Post-earnings synthesis: beat/miss, trend comparison, analyst reaction, market response, guidance tone |

### Atomic Tools (deeper dives)

| Tool | Description |
|------|-------------|
| `company_overview` | Company profile, quote, key metrics, and analyst ratings |
| `financial_statements` | Income statement, balance sheet, cash flow (annual/quarterly) |
| `analyst_consensus` | Analyst grades, price targets, and forward estimates |
| `earnings_info` | Historical and upcoming earnings with beat/miss tracking |
| `price_history` | Historical daily prices with technical context |
| `stock_search` | Search for stocks by name or ticker |
| `insider_activity` | Insider trading activity and transaction statistics |
| `institutional_ownership` | Top institutional holders and position changes |
| `stock_news` | Recent news and press releases |
| `treasury_rates` | Current Treasury yields and yield curve |
| `economic_calendar` | Upcoming economic events and releases |
| `market_overview` | Sector performance, gainers, losers, most active |
| `earnings_transcript` | Earnings call transcripts with pagination support |
| `revenue_segments` | Revenue breakdown by product and geography |
| `peer_comparison` | Peer group valuation and performance comparison |
| `dividends_info` | Dividend history, yield, growth, and payout analysis |
| `earnings_calendar` | Upcoming earnings dates with optional symbol filter |
| `etf_lookup` | ETF holdings or stock ETF exposure (dual-mode with auto-detect) |
| `estimate_revisions` | Analyst sentiment momentum: forward estimates, grade changes, beat rate |

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An [FMP API key](https://financialmodelingprep.com/developer/docs/)

### Install

```bash
uv sync
```

### Configure

Set your API key as an environment variable:

```bash
export FMP_API_KEY=your_api_key_here
```

Or create a `.env` file:

```
FMP_API_KEY=your_api_key_here
```

### Run

```bash
uv run fastmcp run server.py
```

### Claude Desktop / Claude Code

Add to your MCP config:

```json
{
  "mcpServers": {
    "fmp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fmp", "fastmcp", "run", "server.py"],
      "env": {
        "FMP_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Testing

```bash
uv run pytest tests/ -v
```

All tools are tested with mocked API responses using [respx](https://github.com/lundberg/respx).

## Architecture

```
server.py          # FastMCP entry point, registers all tool modules
fmp_client.py      # Async HTTP client with TTL caching and graceful error handling
tools/
  overview.py      # company_overview, stock_search
  financials.py    # financial_statements, revenue_segments
  valuation.py     # analyst_consensus, peer_comparison, estimate_revisions
  market.py        # price_history, earnings_info, dividends_info, earnings_calendar, etf_lookup
  ownership.py     # insider_activity, institutional_ownership
  news.py          # stock_news
  macro.py         # treasury_rates, economic_calendar, market_overview
  transcripts.py   # earnings_transcript (with pagination)
  workflows.py     # stock_brief, market_context, earnings_setup, fair_value_estimate, earnings_postmortem
```

Key design decisions:
- **Module pattern**: Each tool file exports `register(mcp, client)` to keep tools organized
- **Parallel fetches**: Workflow tools use `asyncio.gather()` to call multiple endpoints concurrently
- **Graceful degradation**: `FMPClient.get_safe()` returns defaults on error so composite tools return partial data instead of failing entirely
- **In-memory TTL cache**: Avoids redundant API calls with configurable TTLs per data type (60s for quotes, 24h for profiles)

## License

MIT
