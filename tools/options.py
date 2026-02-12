"""Options chain tool via Polygon.io."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from polygon_client import PolygonClient


def register(mcp: FastMCP, polygon_client: PolygonClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Options Chain",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def options_chain(
        symbol: str,
        expiration_date: str | None = None,
        contract_type: str | None = None,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 50,
    ) -> dict:
        """Get options chain with Greeks, IV, open interest, and bid/ask.

        Returns contracts grouped by expiration with delta, gamma, theta, vega,
        implied volatility, open interest, and volume. Includes put/call ratio
        summary per expiration.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            expiration_date: Filter to specific expiration (YYYY-MM-DD)
            contract_type: Filter by "call" or "put"
            strike_gte: Minimum strike price
            strike_lte: Maximum strike price
            limit: Max contracts to return (default 50, max 250)
        """
        symbol = symbol.upper().strip()
        limit = max(1, min(limit, 250))

        params: dict = {"limit": limit}
        if expiration_date:
            params["expiration_date"] = expiration_date
        if contract_type:
            ct = contract_type.lower().strip()
            if ct not in ("call", "put"):
                return {"error": f"Invalid contract_type '{contract_type}'. Use 'call' or 'put'."}
            params["contract_type"] = ct
        if strike_gte is not None:
            params["strike_price.gte"] = strike_gte
        if strike_lte is not None:
            params["strike_price.lte"] = strike_lte

        data = await polygon_client.get_safe(
            f"/v3/snapshot/options/{symbol}",
            params=params,
            cache_ttl=polygon_client.TTL_REALTIME,
        )

        if not data or not isinstance(data, dict):
            return {"error": f"No options data found for '{symbol}'"}

        results = data.get("results", [])
        if not results:
            return {"error": f"No options contracts found for '{symbol}' with given filters"}

        # Group by expiration
        by_expiration: dict[str, list[dict]] = {}
        for contract in results:
            details = contract.get("details", {})
            greeks = contract.get("greeks", {})
            day = contract.get("day", {})
            last_quote = contract.get("last_quote", {})

            exp = details.get("expiration_date", "unknown")
            entry = {
                "ticker": details.get("ticker"),
                "strike": details.get("strike_price"),
                "type": details.get("contract_type"),
                "expiration": exp,
                "greeks": {
                    "delta": greeks.get("delta"),
                    "gamma": greeks.get("gamma"),
                    "theta": greeks.get("theta"),
                    "vega": greeks.get("vega"),
                },
                "iv": contract.get("implied_volatility"),
                "open_interest": contract.get("open_interest"),
                "volume": day.get("volume"),
                "last_price": day.get("close"),
                "bid": last_quote.get("bid"),
                "ask": last_quote.get("ask"),
                "bid_size": last_quote.get("bid_size"),
                "ask_size": last_quote.get("ask_size"),
            }

            by_expiration.setdefault(exp, []).append(entry)

        # Sort contracts within each expiration by strike
        for exp in by_expiration:
            by_expiration[exp].sort(key=lambda c: c.get("strike") or 0)

        # Build per-expiration summaries
        expirations = []
        total_calls = 0
        total_puts = 0
        total_call_oi = 0
        total_put_oi = 0

        for exp in sorted(by_expiration.keys()):
            contracts = by_expiration[exp]
            calls = [c for c in contracts if c.get("type") == "call"]
            puts = [c for c in contracts if c.get("type") == "put"]

            call_oi = sum(c.get("open_interest") or 0 for c in calls)
            put_oi = sum(c.get("open_interest") or 0 for c in puts)
            pc_ratio = round(put_oi / call_oi, 2) if call_oi > 0 else None

            total_calls += len(calls)
            total_puts += len(puts)
            total_call_oi += call_oi
            total_put_oi += put_oi

            expirations.append({
                "expiration": exp,
                "contract_count": len(contracts),
                "call_count": len(calls),
                "put_count": len(puts),
                "call_open_interest": call_oi,
                "put_open_interest": put_oi,
                "put_call_oi_ratio": pc_ratio,
                "contracts": contracts,
            })

        overall_pc_ratio = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

        return {
            "symbol": symbol,
            "total_contracts": sum(len(e["contracts"]) for e in expirations),
            "summary": {
                "total_calls": total_calls,
                "total_puts": total_puts,
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
                "overall_put_call_ratio": overall_pc_ratio,
            },
            "expirations": expirations,
            "source": "polygon.io",
        }
