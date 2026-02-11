"""Analyst consensus and valuation tools."""

from __future__ import annotations

import asyncio
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
            "title": "Analyst Consensus",
            "readOnlyHint": True,
        }
    )
    async def analyst_consensus(symbol: str) -> dict:
        """Get Wall Street analyst consensus: price targets, ratings, and buy/sell distribution.

        Returns analyst count, consensus/high/low price targets, upside percentage,
        buy/hold/sell breakdown, and FMP's own rating.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        targets_data, grades_data, rating_data, quote_data = await asyncio.gather(
            client.get_safe(
                "/stable/price-target-consensus",
                params={"symbol": symbol},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/upgrades-downgrades-consensus",
                params={"symbol": symbol},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/ratings-snapshot",
                params={"symbol": symbol},
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                f"/api/v3/quote/{symbol}",
                cache_ttl=client.TTL_REALTIME,
                default=[],
            ),
        )

        targets = _safe_first(targets_data)
        grades = _safe_first(grades_data)
        rating = _safe_first(rating_data)
        quote = _safe_first(quote_data)

        if not targets and not grades and not rating:
            return {"error": f"No analyst data found for '{symbol}'"}

        current_price = quote.get("price")

        # Calculate upside from consensus target
        consensus_target = targets.get("targetConsensus")
        upside_pct = None
        if current_price and consensus_target:
            upside_pct = round((consensus_target / current_price - 1) * 100, 2)

        result = {
            "symbol": symbol,
            "current_price": current_price,
            "price_targets": {
                "consensus": consensus_target,
                "high": targets.get("targetHigh"),
                "low": targets.get("targetLow"),
                "median": targets.get("targetMedian"),
                "upside_pct": upside_pct,
            },
            "analyst_grades": {
                "buy": grades.get("buy"),
                "overweight": grades.get("overweight"),
                "hold": grades.get("hold"),
                "underweight": grades.get("underweight"),
                "sell": grades.get("sell"),
                "consensus": grades.get("consensus"),
            },
            "fmp_rating": {
                "rating": rating.get("rating"),
                "score": rating.get("ratingScore"),
                "dcf_score": rating.get("ratingDetailsDCFScore"),
                "roe_score": rating.get("ratingDetailsROEScore"),
                "roa_score": rating.get("ratingDetailsROAScore"),
                "de_score": rating.get("ratingDetailsDEScore"),
                "pe_score": rating.get("ratingDetailsPEScore"),
                "pb_score": rating.get("ratingDetailsPBScore"),
            },
        }

        # Flag partial data
        errors = []
        if not targets:
            errors.append("price target data unavailable")
        if not grades:
            errors.append("analyst grades unavailable")
        if not rating:
            errors.append("FMP rating unavailable")
        if errors:
            result["_warnings"] = errors

        return result
