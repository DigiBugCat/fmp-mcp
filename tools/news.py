"""Stock news, press release, and M&A activity tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


# Event keywords for flagging important news
_EVENT_KEYWORDS = {
    "earnings": ["earnings", "quarterly results", "q1 ", "q2 ", "q3 ", "q4 ", "fiscal"],
    "guidance": ["guidance", "outlook", "forecast", "raises", "lowers"],
    "fda": ["fda", "approval", "clinical trial", "phase "],
    "merger_acquisition": ["acquisition", "acquire", "merger", "takeover", "buyout"],
    "dividend": ["dividend", "distribution", "payout"],
    "restructuring": ["restructuring", "layoff", "cost cutting", "reorganization"],
    "leadership": ["ceo", "cfo", "appoints", "resignation", "board of directors"],
    "regulatory": ["sec", "lawsuit", "investigation", "compliance", "settlement"],
}


def _detect_event(title: str) -> str | None:
    """Detect major event type from headline."""
    title_lower = title.lower()
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            return event_type
    return None


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Stock News",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def stock_news(symbol: str, limit: int = 20) -> dict:
        """Get recent news articles and press releases for a stock.

        Merges news and press releases, deduplicates by title similarity,
        and sorts by date. Flags major event types (earnings, FDA, M&A, etc.).

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            limit: Max total items to return (default 20)
        """
        symbol = symbol.upper().strip()

        news_data, press_data = await asyncio.gather(
            client.get_safe(
                "/stable/news/stock",
                params={"symbol": symbol, "limit": limit},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
            client.get_safe(
                "/stable/news/press-releases",
                params={"symbol": symbol, "limit": 10},
                cache_ttl=client.TTL_HOURLY,
                default=[],
            ),
        )

        news_list = news_data if isinstance(news_data, list) else []
        press_list = press_data if isinstance(press_data, list) else []

        if not news_list and not press_list:
            return {"error": f"No news found for '{symbol}'"}

        # Normalize both sources into common format
        items = []
        seen_titles = set()

        for n in news_list:
            title = n.get("title", "")
            title_key = title.lower().strip()[:80]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            items.append({
                "title": title,
                "date": n.get("publishedDate"),
                "source": n.get("site") or n.get("source"),
                "url": n.get("url"),
                "snippet": (n.get("text") or "")[:300],
                "type": "news",
                "event_flag": _detect_event(title),
            })

        for p in press_list:
            title = p.get("title", "")
            title_key = title.lower().strip()[:80]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            items.append({
                "title": title,
                "date": p.get("publishedDate") or p.get("date"),
                "source": p.get("publisher") or "Press Release",
                "url": p.get("url"),
                "snippet": (p.get("text") or "")[:300],
                "type": "press_release",
                "event_flag": _detect_event(title),
            })

        # Sort by date descending (newest first)
        items.sort(key=lambda x: x.get("date") or "", reverse=True)
        items = items[:limit]

        result = {
            "symbol": symbol,
            "articles": items,
            "count": len(items),
        }

        _warnings = []
        if not news_list:
            _warnings.append("news articles unavailable")
        if not press_list:
            _warnings.append("press releases unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

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
