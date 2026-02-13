"""Commodity, crypto, and forex quote tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools._helpers import TTL_REALTIME, _as_dict, _as_list, _safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_data import AsyncFMPDataClient


def register(mcp: FastMCP, client: AsyncFMPDataClient) -> None:
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
        return await _fetch_asset_quotes(client, "commodity", symbol, limit)

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
        return await _fetch_asset_quotes(client, "crypto", symbol, limit)

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
        return await _fetch_asset_quotes(client, "forex", symbol, limit)


async def _fetch_asset_quotes(
    client: AsyncFMPDataClient,
    asset_type: str,
    symbol: str | None,
    limit: int,
) -> dict:
    limit = max(1, min(limit, 50))

    if symbol:
        symbol = symbol.upper().strip()
        data = await _safe_call(
            client.company.get_quote,
            symbol=symbol,
            ttl=TTL_REALTIME,
            default=None,
        )
        quote = _as_dict(data)
        if not quote:
            return {"error": f"No {asset_type} quote found for '{symbol}'"}

        return {
            "symbol": symbol,
            "mode": "single",
            "asset_type": asset_type,
            "price": quote.get("price"),
            "change": quote.get("change"),
            "change_pct": quote.get("changePercentage") or quote.get("changesPercentage"),
            "day_low": quote.get("dayLow"),
            "day_high": quote.get("dayHigh"),
            "year_low": quote.get("yearLow"),
            "year_high": quote.get("yearHigh"),
            "volume": quote.get("volume"),
            "name": quote.get("name"),
        }

    if asset_type == "commodity":
        data = await _safe_call(client.batch.get_commodity_quotes, ttl=TTL_REALTIME, default=[])
    elif asset_type == "crypto":
        data = await _safe_call(client.batch.get_crypto_quotes, ttl=TTL_REALTIME, default=[])
    else:
        data = await _safe_call(client.batch.get_forex_quotes, ttl=TTL_REALTIME, default=[])

    batch_list = _as_list(data)
    if not batch_list:
        return {"error": f"No {asset_type} batch quotes available"}

    batch_list.sort(key=lambda x: abs(x.get("change") or 0), reverse=True)
    quotes = []
    for q in batch_list[:limit]:
        change = q.get("change")
        price = q.get("price")
        change_pct = q.get("changePercentage") or q.get("changesPercentage")
        if change_pct is None and change is not None and price is not None:
            prev = price - change
            if prev != 0:
                change_pct = round(change / prev * 100, 2)
        quotes.append(
            {
                "symbol": q.get("symbol"),
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "volume": q.get("volume"),
            }
        )

    return {
        "mode": "batch",
        "asset_type": asset_type,
        "count": len(quotes),
        "quotes": quotes,
    }
