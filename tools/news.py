"""Market news, press release, and M&A activity tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


# Routing table: category -> (search endpoint, latest endpoint, supports symbol?)
_NEWS_ROUTES = {
    "stock": {
        "search": "/stable/news/stock",
        "latest": "/stable/news/stock-latest",
        "has_symbol": True,
    },
    "press_releases": {
        "search": "/stable/news/press-releases",
        "latest": "/stable/news/press-releases-latest",
        "has_symbol": True,
    },
    "crypto": {
        "search": "/stable/news/crypto",
        "latest": "/stable/news/crypto-latest",
        "has_symbol": True,
    },
    "forex": {
        "search": "/stable/news/forex",
        "latest": "/stable/news/forex-latest",
        "has_symbol": True,
    },
    "general": {
        "search": None,
        "latest": "/stable/news/general-latest",
        "has_symbol": False,
    },
}


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Market News",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def market_news(
        category: str = "stock",
        symbol: str | None = None,
        page: int = 0,
        limit: int = 20,
    ) -> dict:
        """Get news articles across stocks, crypto, forex, and macro.

        Pick a category based on what you need:

        - "stock": Equity market news — analyst commentary, price targets,
          regulatory developments. Sources: Motley Fool, Zacks, MarketWatch,
          Reuters, CNBC, SeekingAlpha. Pass a symbol for company-specific news,
          or omit for the latest firehose across all tickers.

        - "press_releases": Official corporate filings from wire services —
          earnings reports, dividend announcements, M&A disclosures. Sources:
          Business Wire, PRNewsWire, GlobeNewsWire. Pass a symbol to filter
          (note: FMP's symbol matching is loose, expect some noise).

        - "crypto": Cryptocurrency news — ETF flows, protocol updates, token
          analysis. Sources: NewsBTC, CoinTelegraph, CryptoPotato, CoinDesk.
          Pass a crypto symbol like "BTCUSD" or "ETHUSD" to filter.

        - "forex": Currency pair and precious metals news — central bank
          commentary, technical analysis, pair-specific forecasts. Sources:
          FXStreet, Orbex, FXEmpire. Pass a pair like "EURUSD" or "XAUUSD".
          Also covers gold (XAUUSD) and silver (XAGUSD).

        - "general": Macro and market-wide news with no specific ticker —
          jobs reports, Fed decisions, yield movements, broad sentiment.
          Sources: WSJ, CNBC, Reuters, Benzinga. Symbol param is ignored.

        Use page param to paginate through results (0-indexed).

        Args:
            category: News category - "stock", "press_releases", "crypto", "forex", "general"
            symbol: Optional ticker to search for (ignored for "general")
            page: Page number for pagination (default 0)
            limit: Max articles per page (default 20)
        """
        category = category.lower().strip()
        if category not in _NEWS_ROUTES:
            return {"error": f"Invalid category '{category}'. Use: {', '.join(_NEWS_ROUTES.keys())}"}

        route = _NEWS_ROUTES[category]
        limit = max(1, min(limit, 50))
        page = max(0, page)

        # Decide which endpoint to hit
        if symbol and route["has_symbol"]:
            symbol = symbol.upper().strip()
            path = route["search"]
            params: dict = {"symbols": symbol, "page": page, "limit": limit}
        else:
            path = route["latest"]
            params = {"page": page, "limit": limit}
            if symbol and not route["has_symbol"]:
                symbol = None  # general doesn't support symbol

        data = await client.get_safe(
            path,
            params=params,
            cache_ttl=client.TTL_REALTIME,
            default=[],
        )

        articles_list = data if isinstance(data, list) else []

        if not articles_list:
            msg = f"No {category} news found"
            if symbol:
                msg += f" for '{symbol}'"
            msg += f" (page {page})"
            return {"error": msg}

        articles = []
        for a in articles_list:
            articles.append({
                "title": a.get("title"),
                "date": a.get("publishedDate"),
                "symbol": a.get("symbol"),
                "source": a.get("site") or a.get("publisher"),
                "url": a.get("url"),
                "snippet": (a.get("text") or "")[:300],
            })

        return {
            "category": category,
            "symbol": symbol,
            "page": page,
            "count": len(articles),
            "articles": articles,
        }

    @mcp.tool(
        annotations={
            "title": "M&A Activity",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def mna_activity(
        symbol: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Get merger and acquisition activity.

        Dual mode: pass a symbol to search for M&A involving that company,
        or omit to see latest M&A filings market-wide.

        Args:
            symbol: Optional stock ticker to search for (e.g. "AAPL")
            limit: Max results to return (default 20)
        """
        limit = max(1, min(limit, 50))

        if symbol:
            symbol = symbol.upper().strip()
            data = await client.get_safe(
                "/stable/mergers-acquisitions-search",
                params={"name": symbol, "limit": limit},
                cache_ttl=client.TTL_HOURLY,
                default=[],
            )
        else:
            data = await client.get_safe(
                "/stable/mergers-acquisitions-latest",
                params={"page": 0, "limit": limit},
                cache_ttl=client.TTL_HOURLY,
                default=[],
            )

        entries = data if isinstance(data, list) else []

        if not entries:
            msg = "No M&A activity found"
            if symbol:
                msg += f" for '{symbol}'"
            return {"error": msg}

        # Sort by transaction date descending
        entries.sort(key=lambda x: x.get("transactionDate") or "", reverse=True)

        deals = []
        for e in entries[:limit]:
            deals.append({
                "symbol": e.get("symbol"),
                "company": e.get("companyName"),
                "targeted_company": e.get("targetedCompanyName"),
                "targeted_symbol": e.get("targetedSymbol"),
                "transaction_date": e.get("transactionDate"),
                "accepted_date": e.get("acceptedDate"),
                "filing_url": e.get("link"),
            })

        return {
            "symbol": symbol,
            "count": len(deals),
            "deals": deals,
        }
