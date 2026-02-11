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
        sym_params = {"symbol": symbol}

        targets_data, grades_data, rating_data, quote_data = await asyncio.gather(
            client.get_safe(
                "/stable/price-target-consensus",
                params=sym_params,
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/grades-consensus",
                params=sym_params,
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/ratings-snapshot",
                params=sym_params,
                cache_ttl=client.TTL_6H,
                default=[],
            ),
            client.get_safe(
                "/stable/quote",
                params=sym_params,
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
                "strong_buy": grades.get("strongBuy"),
                "buy": grades.get("buy"),
                "hold": grades.get("hold"),
                "sell": grades.get("sell"),
                "strong_sell": grades.get("strongSell"),
                "consensus": grades.get("consensus"),
            },
            "fmp_rating": {
                "rating": rating.get("rating"),
                "overall_score": rating.get("overallScore"),
                "dcf_score": rating.get("discountedCashFlowScore"),
                "roe_score": rating.get("returnOnEquityScore"),
                "roa_score": rating.get("returnOnAssetsScore"),
                "de_score": rating.get("debtToEquityScore"),
                "pe_score": rating.get("priceToEarningsScore"),
                "pb_score": rating.get("priceToBookScore"),
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

    @mcp.tool(
        annotations={
            "title": "Peer Comparison",
            "readOnlyHint": True,
        }
    )
    async def peer_comparison(symbol: str) -> dict:
        """Compare a stock's valuation and growth metrics against its peers.

        Finds FMP-identified peers, then compares P/E, P/S, EV/EBITDA,
        growth rates, and margins. Shows target's premium/discount to peer median
        and rank within the group.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()

        # Step 1: Get peer list
        peers_data = await client.get_safe(
            "/stable/company-peer",
            params={"symbol": symbol},
            cache_ttl=client.TTL_DAILY,
            default=[],
        )

        peers_list = peers_data if isinstance(peers_data, list) else []
        if not peers_list:
            return {"error": f"No peer data found for '{symbol}'"}

        # Extract peer symbols from the response
        # FMP returns [{"symbol": "AAPL", "peersList": ["MSFT","GOOGL",...]}]
        peer_entry = _safe_first(peers_list)
        peer_symbols = peer_entry.get("peersList", [])
        if not peer_symbols:
            return {"error": f"No peers identified for '{symbol}'"}

        # Limit to 10 peers to avoid excessive API calls
        peer_symbols = peer_symbols[:10]

        # Step 2: Fetch ratios and key metrics for target + all peers in parallel
        all_symbols = [symbol] + peer_symbols

        async def _fetch_metrics(sym: str) -> dict:
            ratios, metrics = await asyncio.gather(
                client.get_safe(
                    "/stable/ratios-ttm",
                    params={"symbol": sym},
                    cache_ttl=client.TTL_HOURLY,
                    default=[],
                ),
                client.get_safe(
                    "/stable/key-metrics-ttm",
                    params={"symbol": sym},
                    cache_ttl=client.TTL_HOURLY,
                    default=[],
                ),
            )
            r = _safe_first(ratios)
            m = _safe_first(metrics)
            return {
                "symbol": sym,
                "pe_ttm": r.get("priceToEarningsRatioTTM"),
                "ps_ttm": r.get("priceToSalesRatioTTM"),
                "ev_ebitda_ttm": r.get("enterpriseValueMultipleTTM"),
                "pb_ttm": r.get("priceToBookRatioTTM"),
                "roe_ttm": r.get("returnOnEquityTTM"),
                "gross_margin_ttm": r.get("grossProfitMarginTTM"),
                "net_margin_ttm": r.get("netProfitMarginTTM"),
                "revenue_growth_ttm": m.get("revenuePerShareTTM"),
                "market_cap": m.get("marketCapTTM"),
            }

        all_metrics = await asyncio.gather(*[_fetch_metrics(s) for s in all_symbols])

        target_metrics = all_metrics[0]
        peer_metrics = [m for m in all_metrics[1:] if m.get("pe_ttm") is not None or m.get("ps_ttm") is not None]

        if not peer_metrics:
            return {
                "symbol": symbol,
                "target": target_metrics,
                "error": "Could not retrieve metrics for any peers",
            }

        # Step 3: Calculate peer medians and target premium/discount
        def _median(values: list[float]) -> float | None:
            clean = [v for v in values if v is not None and isinstance(v, (int, float))]
            if not clean:
                return None
            clean.sort()
            n = len(clean)
            if n % 2 == 0:
                return round((clean[n // 2 - 1] + clean[n // 2]) / 2, 4)
            return round(clean[n // 2], 4)

        def _premium_discount(target_val, median_val) -> float | None:
            if target_val is None or median_val is None or median_val == 0:
                return None
            return round((target_val / median_val - 1) * 100, 2)

        def _rank(target_val, all_vals: list, higher_better: bool = False) -> str | None:
            clean = [(v, i) for i, v in enumerate(all_vals) if v is not None]
            if not clean or target_val is None:
                return None
            clean.sort(key=lambda x: x[0], reverse=higher_better)
            for rank, (v, i) in enumerate(clean, 1):
                if i == 0:  # target is always index 0
                    return f"{rank}/{len(clean)}"
            return None

        comparison_metrics = ["pe_ttm", "ps_ttm", "ev_ebitda_ttm", "pb_ttm", "roe_ttm", "gross_margin_ttm", "net_margin_ttm"]
        higher_better = {"roe_ttm", "gross_margin_ttm", "net_margin_ttm"}

        comparisons = {}
        for metric in comparison_metrics:
            peer_vals = [m.get(metric) for m in peer_metrics]
            all_vals = [target_metrics.get(metric)] + peer_vals
            med = _median(peer_vals)
            comparisons[metric] = {
                "target": target_metrics.get(metric),
                "peer_median": med,
                "premium_discount_pct": _premium_discount(target_metrics.get(metric), med),
                "rank": _rank(target_metrics.get(metric), all_vals, metric in higher_better),
            }

        result = {
            "symbol": symbol,
            "peers": peer_symbols,
            "peer_count": len(peer_metrics),
            "comparisons": comparisons,
            "peer_details": peer_metrics,
        }

        return result
