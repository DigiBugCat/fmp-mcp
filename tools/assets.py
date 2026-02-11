"""Commodity, crypto, and forex quote tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def _safe_first(data: list | None) -> dict:
    if isinstance(data, list) and data:
        return data[0]
    return {}


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Commodity Quotes",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def commodity_quotes(
        symbol: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Get commodity price quotes.

        Pass a symbol for a single quote (e.g. "GCUSD" for gold),
        or omit for a market overview of all commodities sorted by top movers.

        Args:
            symbol: Optional commodity symbol (e.g. "GCUSD", "CLUSD")
            limit: Max results for batch mode (default 10)
        """
        return await _fetch_asset_quotes(
            client, "commodity", symbol, limit,
            single_path="/stable/quote",
            batch_path="/stable/batch-commodity-quotes",
        )

    @mcp.tool(
        annotations={
            "title": "Crypto Quotes",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def crypto_quotes(
        symbol: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Get cryptocurrency price quotes.

        Pass a symbol for a single quote (e.g. "BTCUSD"),
        or omit for a market overview of all cryptos sorted by top movers.

        Args:
            symbol: Optional crypto symbol (e.g. "BTCUSD", "ETHUSD")
            limit: Max results for batch mode (default 10)
        """
        return await _fetch_asset_quotes(
            client, "crypto", symbol, limit,
            single_path="/stable/quote",
            batch_path="/stable/batch-crypto-quotes",
        )

    @mcp.tool(
        annotations={
            "title": "Forex Quotes",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def forex_quotes(
        symbol: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Get forex currency pair quotes.

        Pass a symbol for a single quote (e.g. "EURUSD"),
        or omit for a market overview of all pairs sorted by top movers.

        Args:
            symbol: Optional forex pair (e.g. "EURUSD", "GBPUSD")
            limit: Max results for batch mode (default 10)
        """
        return await _fetch_asset_quotes(
            client, "forex", symbol, limit,
            single_path="/stable/quote",
            batch_path="/stable/batch-forex-quotes",
        )


async def _fetch_asset_quotes(
    client: "FMPClient",
    asset_type: str,
    symbol: str | None,
    limit: int,
    single_path: str,
    batch_path: str,
) -> dict:
    """Shared logic for commodity/crypto/forex quote tools."""
    limit = max(1, min(limit, 50))

    if symbol:
        symbol = symbol.upper().strip()
        data = await client.get_safe(
            single_path,
            params={"symbol": symbol},
            cache_ttl=client.TTL_REALTIME,
            default=[],
        )

        quote = _safe_first(data)
        if not quote:
            return {"error": f"No {asset_type} quote found for '{symbol}'"}

        return {
            "symbol": symbol,
            "mode": "single",
            "asset_type": asset_type,
            "price": quote.get("price"),
            "change": quote.get("change"),
            "change_pct": quote.get("changesPercentage"),
            "day_low": quote.get("dayLow"),
            "day_high": quote.get("dayHigh"),
            "year_low": quote.get("yearLow"),
            "year_high": quote.get("yearHigh"),
            "volume": quote.get("volume"),
            "name": quote.get("name"),
        }

    # Batch mode
    data = await client.get_safe(
        batch_path,
        cache_ttl=client.TTL_REALTIME,
        default=[],
    )

    batch_list = data if isinstance(data, list) else []

    if not batch_list:
        return {"error": f"No {asset_type} batch quotes available"}

    # Sort by absolute change descending (top movers)
    batch_list.sort(key=lambda x: abs(x.get("change") or 0), reverse=True)

    quotes = []
    for q in batch_list[:limit]:
        quotes.append({
            "symbol": q.get("symbol"),
            "price": q.get("price"),
            "change": q.get("change"),
            "volume": q.get("volume"),
        })

    return {
        "mode": "batch",
        "asset_type": asset_type,
        "count": len(quotes),
        "quotes": quotes,
    }
