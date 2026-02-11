"""Workflow tools that orchestrate multiple FMP endpoints for research questions."""

from __future__ import annotations

import asyncio
import statistics
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


# --- Helpers ---


def _safe_first(data: list | None) -> dict:
    if isinstance(data, list) and data:
        return data[0]
    return {}


def _pct_change(new: float | None, old: float | None) -> float | None:
    """Safe percentage change."""
    if new is None or old is None or old == 0:
        return None
    return round((new / old - 1) * 100, 2)


def _classify_signal(
    score: float, thresholds: tuple[float, float] = (-0.5, 0.5)
) -> str:
    """Convert a numeric score to a label."""
    if score <= thresholds[0]:
        return "bearish"
    if score >= thresholds[1]:
        return "bullish"
    return "neutral"


def _filter_recent(
    items: list[dict], days: int, date_field: str = "date"
) -> list[dict]:
    """Filter list by recency."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [i for i in items if (i.get(date_field) or "") >= cutoff]


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and isinstance(v, (int, float))]
    if not clean:
        return None
    return round(statistics.median(clean), 4)


def _calc_performance(current: float, history: list[dict], days: int) -> float | None:
    if not current or len(history) < days:
        return None
    old_price = history[min(days - 1, len(history) - 1)].get("close")
    if not old_price or old_price == 0:
        return None
    return round((current / old_price - 1) * 100, 2)


# --- Registration ---


def register(mcp: FastMCP, client: FMPClient) -> None:

    # ================================================================
    # 1. stock_brief — "Give me a quick read on this stock"
    # ================================================================

    @mcp.tool(
        annotations={"title": "Stock Brief", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
    )
    async def stock_brief(symbol: str) -> dict:
        """Quick comprehensive stock snapshot: profile, price action, valuation, analyst consensus, insider signals, and top headlines.

        Replaces the 4-tool chain (overview + price + news + consensus) with a
        single call. Returns momentum across timeframes, SMA positioning,
        valuation multiples, analyst consensus + upside, insider signal, and
        a heuristic quick-take signal.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()
        sym = {"symbol": symbol}

        (
            profile_data, quote_data, ratios_data, history_data,
            grades_data, targets_data, insider_data, news_data,
        ) = await asyncio.gather(
            client.get_safe("/stable/profile", params=sym, cache_ttl=client.TTL_DAILY, default=[]),
            client.get_safe("/stable/quote", params=sym, cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/ratios-ttm", params=sym, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/historical-price-eod/full", params={**sym, "from": (date.today() - timedelta(days=365)).isoformat(), "to": date.today().isoformat()}, cache_ttl=client.TTL_12H, default=[]),
            client.get_safe("/stable/grades-consensus", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/price-target-consensus", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/insider-trading/search", params={**sym, "limit": 50}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/news/stock", params={**sym, "limit": 5}, cache_ttl=client.TTL_REALTIME, default=[]),
        )

        profile = _safe_first(profile_data)
        quote = _safe_first(quote_data)
        ratios = _safe_first(ratios_data)
        grades = _safe_first(grades_data)
        targets = _safe_first(targets_data)
        historical = history_data if isinstance(history_data, list) else []
        insider_list = insider_data if isinstance(insider_data, list) else []
        news_list = news_data if isinstance(news_data, list) else []

        if not profile and not quote:
            return {"error": f"No data found for symbol '{symbol}'"}

        current_price = quote.get("price")
        year_high = quote.get("yearHigh")
        year_low = quote.get("yearLow")
        sma_50 = quote.get("priceAvg50")
        sma_200 = quote.get("priceAvg200")

        # Performance across timeframes
        momentum = {}
        for label, days in [("1w", 5), ("1m", 21), ("3m", 63), ("ytd", None)]:
            if days is None:
                # YTD
                jan1 = date(date.today().year, 1, 1).isoformat()
                ytd_prices = [h for h in historical if (h.get("date") or "") >= jan1]
                if ytd_prices and current_price:
                    oldest = ytd_prices[-1].get("close") if ytd_prices else None
                    momentum["ytd"] = _pct_change(current_price, oldest)
            elif current_price:
                momentum[label] = _calc_performance(current_price, historical, days)

        momentum["sma_50"] = sma_50
        momentum["sma_200"] = sma_200
        momentum["above_50"] = current_price > sma_50 if current_price and sma_50 else None
        momentum["above_200"] = current_price > sma_200 if current_price and sma_200 else None

        from_high_pct = _pct_change(current_price, year_high) if current_price and year_high else None

        # Analyst consensus
        consensus_target = targets.get("targetConsensus")
        upside_pct = _pct_change(consensus_target, current_price) if consensus_target and current_price else None

        # Insider signal (30d)
        cutoff_30 = (date.today() - timedelta(days=30)).isoformat()
        buys_30, sells_30 = 0, 0
        cluster_buyers = set()
        for t in insider_list:
            trade_date = t.get("filingDate", t.get("transactionDate", ""))
            if trade_date < cutoff_30:
                continue
            tx = (t.get("transactionType") or "").lower()
            shares = t.get("securitiesTransacted") or 0
            if "purchase" in tx or "p-purchase" in tx:
                buys_30 += shares
                cluster_buyers.add(t.get("reportingName", ""))
            elif "sale" in tx or "s-sale" in tx:
                sells_30 += shares

        net_30 = buys_30 - sells_30
        insider_signal = "net_buying" if net_30 > 0 else "net_selling" if net_30 < 0 else "neutral"
        cluster_buying = len(cluster_buyers) >= 3

        # News (top 5)
        news_items = []
        for n in news_list[:5]:
            title = n.get("title", "")
            news_items.append({
                "date": n.get("publishedDate"),
                "title": title,
                "source": n.get("site") or n.get("source"),
            })

        # Quick take heuristic
        score = 0
        factors = []
        if upside_pct is not None and upside_pct > 10:
            score += 1
            factors.append(f"analyst upside {upside_pct:.0f}%")
        elif upside_pct is not None and upside_pct < -10:
            score -= 1
            factors.append(f"analyst downside {upside_pct:.0f}%")
        if momentum.get("above_50") and momentum.get("above_200"):
            score += 0.5
            factors.append("above both SMAs")
        elif not momentum.get("above_50") and not momentum.get("above_200"):
            score -= 0.5
            factors.append("below both SMAs")
        if insider_signal == "net_buying":
            score += 0.5
            factors.append("insider buying")
        elif insider_signal == "net_selling":
            score -= 0.3
        consensus_label = grades.get("consensus", "")
        if consensus_label in ("Buy", "Strong Buy"):
            score += 0.5
            factors.append(f"consensus: {consensus_label}")
        elif consensus_label in ("Sell", "Strong Sell"):
            score -= 0.5
            factors.append(f"consensus: {consensus_label}")

        signal = _classify_signal(score)

        result = {
            "symbol": symbol,
            "company_name": profile.get("companyName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "price": {
                "current": current_price,
                "market_cap": quote.get("marketCap"),
                "change_pct": quote.get("changePercentage"),
                "52w_high": year_high,
                "52w_low": year_low,
                "from_high_pct": from_high_pct,
            },
            "momentum": momentum,
            "valuation": {
                "pe": ratios.get("priceToEarningsRatioTTM"),
                "ps": ratios.get("priceToSalesRatioTTM"),
                "ev_ebitda": ratios.get("enterpriseValueMultipleTTM"),
                "peg": ratios.get("priceToEarningsGrowthRatioTTM"),
                "dividend_yield": ratios.get("dividendYieldTTM"),
            },
            "analyst": {
                "consensus": grades.get("consensus"),
                "strong_buy": grades.get("strongBuy"),
                "buy": grades.get("buy"),
                "hold": grades.get("hold"),
                "sell": grades.get("sell"),
                "target": consensus_target,
                "upside_pct": upside_pct,
            },
            "insider": {
                "net_30d": net_30,
                "signal": insider_signal,
                "cluster_buying": cluster_buying,
            },
            "news": news_items,
            "quick_take": {
                "signal": signal,
                "key_factors": factors,
            },
        }

        _warnings = []
        if not profile:
            _warnings.append("profile unavailable")
        if not quote:
            _warnings.append("quote unavailable")
        if not ratios:
            _warnings.append("ratios unavailable")
        if not historical:
            _warnings.append("historical prices unavailable")
        if not grades:
            _warnings.append("analyst grades unavailable")
        if not targets:
            _warnings.append("price targets unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    # ================================================================
    # 2. market_context — "What's the market doing?"
    # ================================================================

    @mcp.tool(
        annotations={"title": "Market Context", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
    )
    async def market_context() -> dict:
        """Full market environment: rates, yield curve, sector rotation, breadth, movers, and economic calendar.

        Combines treasury rates, risk premium, sector performance, biggest
        movers, and upcoming macro events into a single environment snapshot.
        Calculates yield curve spread, rotation signal, breadth signal, and
        overall regime classification.
        """
        today_dt = date.today()
        end_dt = today_dt + timedelta(days=7)

        (
            rates_data, erp_data, calendar_data,
            sectors_data, gainers_data, losers_data, actives_data,
        ) = await asyncio.gather(
            client.get_safe("/stable/treasury-rates", cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/market-risk-premium", cache_ttl=client.TTL_DAILY, default=[]),
            client.get_safe("/stable/economic-calendar", params={"from": today_dt.isoformat(), "to": end_dt.isoformat()}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/sector-performance-snapshot", cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/biggest-gainers", cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/biggest-losers", cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/most-actives", cache_ttl=client.TTL_REALTIME, default=[]),
        )

        latest_rate = _safe_first(rates_data if isinstance(rates_data, list) else [])
        erp_list = erp_data if isinstance(erp_data, list) else []
        calendar_list = calendar_data if isinstance(calendar_data, list) else []
        sectors_list = sectors_data if isinstance(sectors_data, list) else []
        gainers_list = gainers_data if isinstance(gainers_data, list) else []
        losers_list = losers_data if isinstance(losers_data, list) else []
        actives_list = actives_data if isinstance(actives_data, list) else []

        if not latest_rate and not sectors_list:
            return {"error": "No market data available"}

        # Rates
        y10 = latest_rate.get("year10")
        y2 = latest_rate.get("year2")
        spread_bps = round((y10 - y2) * 100) if y10 is not None and y2 is not None else None
        inverted = (spread_bps or 0) < 0

        us_erp = None
        for entry in erp_list:
            if entry.get("country") == "United States":
                us_erp = entry.get("totalEquityRiskPremium")
                break
        cost_of_equity = round(y10 + us_erp, 2) if y10 is not None and us_erp is not None else None

        # Sector rotation
        sectors_sorted = sorted(sectors_list, key=lambda s: s.get("changesPercentage") or 0, reverse=True)
        leaders = [{"sector": s.get("sector"), "pct": s.get("changesPercentage")} for s in sectors_sorted[:3]]
        laggards = [{"sector": s.get("sector"), "pct": s.get("changesPercentage")} for s in sectors_sorted[-3:]]

        # Rotation signal: risk_on if growth/tech leading, risk_off if defensives leading
        growth_sectors = {"Technology", "Consumer Cyclical", "Communication Services"}
        defensive_sectors = {"Utilities", "Consumer Defensive", "Healthcare"}
        leader_names = {s["sector"] for s in leaders}
        laggard_names = {s["sector"] for s in laggards}

        if leader_names & growth_sectors and laggard_names & defensive_sectors:
            rotation_signal = "risk_on"
        elif leader_names & defensive_sectors and laggard_names & growth_sectors:
            rotation_signal = "risk_off"
        else:
            rotation_signal = "mixed"

        # Breadth
        gainer_pcts = [abs(g.get("changesPercentage") or 0) for g in gainers_list[:10]]
        loser_pcts = [abs(l.get("changesPercentage") or 0) for l in losers_list[:10]]
        avg_gainer = round(statistics.mean(gainer_pcts), 2) if gainer_pcts else 0
        avg_loser = round(statistics.mean(loser_pcts), 2) if loser_pcts else 0
        if avg_gainer > avg_loser * 1.2:
            breadth_signal = "bullish"
        elif avg_loser > avg_gainer * 1.2:
            breadth_signal = "bearish"
        else:
            breadth_signal = "neutral"

        # Movers (top 5)
        def _fmt(m: dict) -> dict:
            return {"symbol": m.get("symbol"), "name": m.get("name"), "price": m.get("price"), "change_pct": m.get("changesPercentage")}

        # Calendar: US high-impact, split today vs this_week
        high_impact_kw = [
            "fed", "fomc", "interest rate", "cpi", "consumer price",
            "nonfarm", "non-farm", "unemployment", "gdp", "pce",
            "retail sales", "ism", "pmi",
        ]
        today_str = today_dt.isoformat()
        today_events, week_events = [], []
        for evt in calendar_list:
            country = (evt.get("country") or "").upper()
            if country != "US":
                continue
            name = (evt.get("event") or "").lower()
            if not any(kw in name for kw in high_impact_kw):
                continue
            formatted = {
                "date": evt.get("date"),
                "event": evt.get("event"),
                "estimate": evt.get("estimate"),
                "previous": evt.get("previous"),
                "impact": evt.get("impact"),
            }
            evt_date = (evt.get("date") or "")[:10]
            if evt_date == today_str:
                today_events.append(formatted)
            else:
                week_events.append(formatted)

        # Environment classification
        themes = []
        if inverted:
            themes.append("yield curve inverted")
        if rotation_signal == "risk_on":
            themes.append("risk-on rotation")
        elif rotation_signal == "risk_off":
            themes.append("risk-off rotation")
        if breadth_signal == "bullish":
            themes.append("strong breadth")
        elif breadth_signal == "bearish":
            themes.append("weak breadth")

        bullish_count = sum(1 for t in [rotation_signal, breadth_signal] if t in ("risk_on", "bullish"))
        bearish_count = sum(1 for t in [rotation_signal, breadth_signal] if t in ("risk_off", "bearish"))
        if inverted:
            bearish_count += 1
        if bullish_count > bearish_count:
            regime = "risk_on"
        elif bearish_count > bullish_count:
            regime = "risk_off"
        else:
            regime = "neutral"

        result = {
            "date": today_str,
            "rates": {
                "10y": y10,
                "2y": y2,
                "spread_bps": spread_bps,
                "inverted": inverted,
                "erp": us_erp,
                "cost_of_equity": cost_of_equity,
            },
            "rotation": {
                "leaders": leaders,
                "laggards": laggards,
                "signal": rotation_signal,
            },
            "breadth": {
                "avg_gainer_pct": avg_gainer,
                "avg_loser_pct": avg_loser,
                "signal": breadth_signal,
            },
            "movers": {
                "gainers": [_fmt(g) for g in gainers_list[:5]],
                "losers": [_fmt(l) for l in losers_list[:5]],
                "most_active": [_fmt(a) for a in actives_list[:5]],
            },
            "calendar": {
                "today": today_events,
                "this_week": week_events,
            },
            "environment": {
                "regime": regime,
                "themes": themes,
            },
        }

        _warnings = []
        if not latest_rate:
            _warnings.append("treasury rates unavailable")
        if not erp_list:
            _warnings.append("risk premium unavailable")
        if not sectors_list:
            _warnings.append("sector data unavailable")
        if not gainers_list and not losers_list:
            _warnings.append("movers data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    # ================================================================
    # 3. earnings_setup — "Should I play this earnings?"
    # ================================================================

    @mcp.tool(
        annotations={"title": "Earnings Setup", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
    )
    async def earnings_setup(symbol: str) -> dict:
        """Pre-earnings positioning analysis: consensus estimates, historical beat/miss rate, analyst momentum, price drift, and insider signals.

        Orchestrates 8 endpoints to answer "should I play this earnings?"
        Returns days until earnings, consensus EPS/revenue, beat rate from
        last 4-8 quarters, analyst upgrade/downgrade momentum, pre-earnings
        price drift, insider net activity, and a heuristic setup signal.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL", "DDOG")
        """
        symbol = symbol.upper().strip()
        sym = {"symbol": symbol}

        (
            profile_data, quote_data, earnings_data, grades_data,
            history_data, insider_data, insider_stats_data, float_data,
        ) = await asyncio.gather(
            client.get_safe("/stable/profile", params=sym, cache_ttl=client.TTL_DAILY, default=[]),
            client.get_safe("/stable/quote", params=sym, cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/earnings", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/grades", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/historical-price-eod/full", params={**sym, "from": (date.today() - timedelta(days=90)).isoformat(), "to": date.today().isoformat()}, cache_ttl=client.TTL_12H, default=[]),
            client.get_safe("/stable/insider-trading/search", params={**sym, "limit": 50}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/insider-trading/statistics", params=sym, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/shares-float", params=sym, cache_ttl=client.TTL_DAILY, default=[]),
        )

        profile = _safe_first(profile_data)
        quote = _safe_first(quote_data)
        earnings_list = earnings_data if isinstance(earnings_data, list) else []
        grades_list = grades_data if isinstance(grades_data, list) else []
        historical = history_data if isinstance(history_data, list) else []
        insider_list = insider_data if isinstance(insider_data, list) else []
        float_info = _safe_first(float_data)

        if not quote and not earnings_list:
            return {"error": f"No data found for symbol '{symbol}'"}

        current_price = quote.get("price")
        today_dt = date.today()
        today_str = today_dt.isoformat()

        # --- Parse earnings: split future vs historical ---
        future_earnings = []
        historical_earnings = []
        for e in earnings_list:
            edate = e.get("date", "")
            if edate > today_str and e.get("eps") is None:
                future_earnings.append(e)
            elif e.get("eps") is not None and e.get("epsEstimated") is not None:
                historical_earnings.append(e)

        # Sort: future ascending, historical descending
        future_earnings.sort(key=lambda e: e.get("date", ""))
        historical_earnings.sort(key=lambda e: e.get("date", ""), reverse=True)

        # Next earnings
        next_earnings = future_earnings[0] if future_earnings else None
        earnings_date = next_earnings.get("date") if next_earnings else None
        days_until = None
        if earnings_date:
            try:
                ed = datetime.strptime(earnings_date, "%Y-%m-%d").date()
                days_until = (ed - today_dt).days
            except ValueError:
                pass

        # Consensus
        consensus = {}
        if next_earnings:
            consensus = {
                "eps": next_earnings.get("epsEstimated"),
                "revenue": next_earnings.get("revenueEstimated"),
                "analyst_count": next_earnings.get("numberOfAnalysts"),
            }

        # Surprise history (last 8 actuals)
        last_8 = historical_earnings[:8]
        surprise_list = []
        for e in last_8:
            actual = e.get("eps")
            estimated = e.get("epsEstimated")
            if actual is not None and estimated is not None and estimated != 0:
                surprise_pct = round((actual - estimated) / abs(estimated) * 100, 2)
                beat = actual > estimated
            else:
                surprise_pct = None
                beat = None
            surprise_list.append({
                "date": e.get("date"),
                "actual": actual,
                "estimate": estimated,
                "surprise_pct": surprise_pct,
                "beat": beat,
            })

        beats = [s for s in surprise_list if s.get("beat") is True]
        beat_rate = round(len(beats) / len(surprise_list) * 100) if surprise_list else None
        avg_surprise = round(statistics.mean([s["surprise_pct"] for s in surprise_list if s.get("surprise_pct") is not None]), 2) if any(s.get("surprise_pct") is not None for s in surprise_list) else None

        # Analyst momentum from /stable/grades
        recent_30d = _filter_recent(grades_list, 30)
        recent_90d = _filter_recent(grades_list, 90)

        upgrades_30 = len([g for g in recent_30d if (g.get("action") or "").lower() in ("upgrade", "initiate")])
        downgrades_30 = len([g for g in recent_30d if (g.get("action") or "").lower() == "downgrade"])
        upgrades_90 = len([g for g in recent_90d if (g.get("action") or "").lower() in ("upgrade", "initiate")])
        downgrades_90 = len([g for g in recent_90d if (g.get("action") or "").lower() == "downgrade"])

        recent_actions = []
        for g in grades_list[:5]:
            recent_actions.append({
                "firm": g.get("gradingCompany"),
                "action": g.get("action"),
                "new_grade": g.get("newGrade"),
                "date": g.get("date"),
            })

        analyst_net_30 = upgrades_30 - downgrades_30
        if analyst_net_30 > 0:
            analyst_signal = "positive"
        elif analyst_net_30 < 0:
            analyst_signal = "negative"
        else:
            analyst_signal = "neutral"

        # Price drift (5d, 20d)
        drift_5d = _calc_performance(current_price, historical, 5)
        drift_20d = _calc_performance(current_price, historical, 20)

        # Distance from 52w high
        year_high = quote.get("yearHigh")
        from_52w_high = _pct_change(current_price, year_high) if current_price and year_high else None

        # Insider signal (30d)
        cutoff_30 = (today_dt - timedelta(days=30)).isoformat()
        buys_30, sells_30 = 0, 0
        cluster_buyers = set()
        notable_insiders = []
        for t in insider_list:
            trade_date = t.get("filingDate", t.get("transactionDate", ""))
            if trade_date < cutoff_30:
                continue
            tx = (t.get("transactionType") or "").lower()
            shares = t.get("securitiesTransacted") or 0
            name = t.get("reportingName", "")
            if "purchase" in tx or "p-purchase" in tx:
                buys_30 += shares
                cluster_buyers.add(name)
                notable_insiders.append({"name": name, "type": "buy", "shares": shares, "date": trade_date})
            elif "sale" in tx or "s-sale" in tx:
                sells_30 += shares
                notable_insiders.append({"name": name, "type": "sell", "shares": shares, "date": trade_date})

        net_30 = buys_30 - sells_30
        cluster = len(cluster_buyers) >= 3

        # --- Setup signal heuristic ---
        setup_score = 0
        key_factors = []

        # Beat history weight
        if beat_rate is not None:
            if beat_rate >= 75:
                setup_score += 1
                key_factors.append(f"beat rate {beat_rate}%")
            elif beat_rate <= 25:
                setup_score -= 1
                key_factors.append(f"miss rate {100 - beat_rate}%")

        # Analyst momentum
        if analyst_signal == "positive":
            setup_score += 0.5
            key_factors.append(f"{upgrades_30} upgrades in 30d")
        elif analyst_signal == "negative":
            setup_score -= 0.5
            key_factors.append(f"{downgrades_30} downgrades in 30d")

        # Insider signal
        if net_30 > 0 or cluster:
            setup_score += 0.5
            key_factors.append("insider buying" + (" (cluster)" if cluster else ""))
        elif net_30 < 0 and abs(net_30) > buys_30 * 2:
            setup_score -= 0.3
            key_factors.append("heavy insider selling")

        # Price drift
        if drift_20d is not None:
            if drift_20d > 5:
                setup_score += 0.3
                key_factors.append(f"positive drift +{drift_20d}%")
            elif drift_20d < -5:
                setup_score -= 0.3
                key_factors.append(f"negative drift {drift_20d}%")

        signal = _classify_signal(setup_score)

        result = {
            "symbol": symbol,
            "company_name": profile.get("companyName"),
            "current_price": current_price,
            "earnings_date": earnings_date,
            "days_until_earnings": days_until,
            "consensus": consensus,
            "surprise_history": {
                "last_quarters": surprise_list[:4],
                "beat_rate": beat_rate,
                "avg_surprise": avg_surprise,
            },
            "analyst_momentum": {
                "upgrades_30d": upgrades_30,
                "downgrades_30d": downgrades_30,
                "upgrades_90d": upgrades_90,
                "downgrades_90d": downgrades_90,
                "recent_actions": recent_actions,
                "signal": analyst_signal,
            },
            "price_action": {
                "drift_5d_pct": drift_5d,
                "drift_20d_pct": drift_20d,
                "from_52w_high_pct": from_52w_high,
            },
            "insider_signal": {
                "net_shares_30d": net_30,
                "cluster_buying": cluster,
                "notable": notable_insiders[:5],
            },
            "setup_summary": {
                "signal": signal,
                "key_factors": key_factors,
            },
        }

        _warnings = []
        if not earnings_list:
            _warnings.append("earnings data unavailable")
        if not grades_list:
            _warnings.append("analyst grades unavailable")
        if not historical:
            _warnings.append("historical prices unavailable")
        if not insider_list:
            _warnings.append("insider data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    # ================================================================
    # 4. fair_value_estimate — "What's this stock worth?"
    # ================================================================

    @mcp.tool(
        annotations={"title": "Fair Value Estimate", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
    )
    async def fair_value_estimate(symbol: str) -> dict:
        """Multi-method fair value estimate with peer context.

        Calculates fair value using PE-based, PS-based, simplified DCF, and
        analyst target methods. Compares current multiples to peer medians.
        Returns a blended fair value, upside/downside, and valuation rating.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
        """
        symbol = symbol.upper().strip()
        sym = {"symbol": symbol}

        # Step 1: Fetch base data for target
        (
            quote_data, income_data, balance_data, cashflow_data,
            metrics_data, ratios_data, estimates_data, targets_data,
            peers_data,
        ) = await asyncio.gather(
            client.get_safe("/stable/quote", params=sym, cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/income-statement", params={**sym, "limit": 4}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/balance-sheet-statement", params={**sym, "limit": 1}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/cash-flow-statement", params={**sym, "limit": 1}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/key-metrics-ttm", params=sym, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/ratios-ttm", params=sym, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/analyst-estimates", params={**sym, "period": "quarter", "limit": 4}, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/price-target-consensus", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/stock-peers", params=sym, cache_ttl=client.TTL_DAILY, default=[]),
        )

        quote = _safe_first(quote_data)
        income_list = income_data if isinstance(income_data, list) else []
        balance = _safe_first(balance_data)
        cashflow = _safe_first(cashflow_data)
        metrics = _safe_first(metrics_data)
        ratios = _safe_first(ratios_data)
        estimates_list = estimates_data if isinstance(estimates_data, list) else []
        targets = _safe_first(targets_data)
        peers_list = peers_data if isinstance(peers_data, list) else []

        if not quote:
            return {"error": f"No data found for symbol '{symbol}'"}

        current_price = quote.get("price")
        market_cap = quote.get("marketCap")

        # Fundamentals
        latest_income = income_list[0] if income_list else {}
        ttm_revenue = latest_income.get("revenue")
        ttm_net_income = latest_income.get("netIncome")
        ttm_fcf = cashflow.get("freeCashFlow")
        total_debt = balance.get("totalDebt") or 0
        cash = balance.get("cashAndCashEquivalents") or 0
        net_debt = total_debt - cash

        # EV
        ev = (market_cap or 0) + total_debt - cash if market_cap else None

        # Shares outstanding (derive from market cap / price)
        shares = round(market_cap / current_price) if market_cap and current_price and current_price > 0 else None

        # Forward estimates: sum next 4 quarters for forward EPS/revenue
        estimates_list.sort(key=lambda e: e.get("date", ""))
        fwd_eps = sum(e.get("epsAvg") or 0 for e in estimates_list[:4]) if estimates_list else None
        fwd_revenue = sum(e.get("revenueAvg") or 0 for e in estimates_list[:4]) if estimates_list else None

        # Growth rates
        rev_growth_fwd = _pct_change(fwd_revenue, ttm_revenue) if fwd_revenue and ttm_revenue else None
        eps_growth_fwd = None
        if fwd_eps and latest_income.get("epsDiluted") and latest_income["epsDiluted"] != 0:
            eps_growth_fwd = _pct_change(fwd_eps, latest_income["epsDiluted"])

        # 3-year revenue CAGR
        rev_cagr_3y = None
        if len(income_list) >= 4:
            start_rev = income_list[3].get("revenue")
            end_rev = income_list[0].get("revenue")
            if start_rev and end_rev and start_rev > 0:
                try:
                    rev_cagr_3y = round(((end_rev / start_rev) ** (1 / 3) - 1) * 100, 2)
                except (ZeroDivisionError, ValueError, OverflowError):
                    pass

        # Step 2: Fetch peer data
        peer_symbols = [p.get("symbol") for p in peers_list if p.get("symbol")][:5]

        async def _fetch_peer(s: str) -> dict:
            r, m = await asyncio.gather(
                client.get_safe("/stable/ratios-ttm", params={"symbol": s}, cache_ttl=client.TTL_HOURLY, default=[]),
                client.get_safe("/stable/key-metrics-ttm", params={"symbol": s}, cache_ttl=client.TTL_HOURLY, default=[]),
            )
            rd = _safe_first(r)
            md = _safe_first(m)
            return {
                "symbol": s,
                "pe": rd.get("priceToEarningsRatioTTM"),
                "ps": rd.get("priceToSalesRatioTTM"),
                "ev_ebitda": rd.get("enterpriseValueMultipleTTM"),
                "p_fcf": rd.get("priceToFreeCashFlowRatioTTM"),
            }

        peer_metrics = await asyncio.gather(*[_fetch_peer(s) for s in peer_symbols]) if peer_symbols else []

        # Peer medians
        peer_pe_med = _median([p["pe"] for p in peer_metrics])
        peer_ps_med = _median([p["ps"] for p in peer_metrics])
        peer_ev_ebitda_med = _median([p["ev_ebitda"] for p in peer_metrics])
        peer_pfcf_med = _median([p["p_fcf"] for p in peer_metrics])

        # Current multiples
        cur_pe = ratios.get("priceToEarningsRatioTTM")
        cur_ps = ratios.get("priceToSalesRatioTTM")
        cur_ev_ebitda = ratios.get("enterpriseValueMultipleTTM")
        cur_pfcf = ratios.get("priceToFreeCashFlowRatioTTM")

        # Premium/discount
        def _prem(cur, med):
            if cur is None or med is None or med == 0:
                return None
            return round((cur / med - 1) * 100, 2)

        # Step 3: Fair value calculations
        # PE-based FV
        pe_fv = round(fwd_eps * peer_pe_med, 2) if fwd_eps and peer_pe_med else None

        # PS-based FV
        ps_fv = None
        if fwd_revenue and peer_ps_med and shares and shares > 0:
            ps_fv = round(fwd_revenue * peer_ps_med / shares, 2)

        # DCF-simplified: (ttm_fcf × (1 + growth) × terminal_multiple) / shares
        dcf_fv = None
        growth_rate = (rev_growth_fwd or 0) / 100
        terminal_multiple = 15  # conservative
        if ttm_fcf and ttm_fcf > 0 and shares and shares > 0:
            dcf_fv = round(ttm_fcf * (1 + growth_rate) * terminal_multiple / shares, 2)

        # Analyst target
        analyst_fv = targets.get("targetConsensus")

        # Blended (equal weight of available methods)
        methods = [v for v in [pe_fv, ps_fv, dcf_fv, analyst_fv] if v is not None]
        blended_fv = round(statistics.mean(methods), 2) if methods else None

        upside_pct = _pct_change(blended_fv, current_price) if blended_fv and current_price else None

        # Valuation rating
        if upside_pct is not None:
            if upside_pct > 15:
                rating = "undervalued"
            elif upside_pct < -15:
                rating = "overvalued"
            else:
                rating = "fairly_valued"
        else:
            rating = "insufficient_data"

        # Quality metrics
        roe = ratios.get("returnOnEquityTTM")
        net_margin = ratios.get("netProfitMarginTTM")
        de_ratio = ratios.get("debtToEquityRatioTTM")

        quality_score = 0
        if roe is not None and roe > 0.15:
            quality_score += 1
        if net_margin is not None and net_margin > 0.10:
            quality_score += 1
        if de_ratio is not None and de_ratio < 1.5:
            quality_score += 1

        # Key drivers
        key_drivers = []
        if upside_pct is not None:
            key_drivers.append(f"blended FV implies {upside_pct:+.1f}% {'upside' if upside_pct > 0 else 'downside'}")
        if pe_fv and current_price:
            key_drivers.append(f"PE-based: ${pe_fv:.0f} vs ${current_price:.0f}")
        if rev_growth_fwd:
            key_drivers.append(f"fwd revenue growth: {rev_growth_fwd:.1f}%")
        confidence = "high" if len(methods) >= 3 else "medium" if len(methods) >= 2 else "low"

        result = {
            "symbol": symbol,
            "current_price": current_price,
            "fundamentals": {
                "market_cap": market_cap,
                "ev": ev,
                "shares": shares,
                "ttm_revenue": ttm_revenue,
                "ttm_net_income": ttm_net_income,
                "ttm_fcf": ttm_fcf,
                "debt": total_debt,
                "cash": cash,
                "net_debt": net_debt,
            },
            "growth": {
                "rev_growth_fwd_pct": rev_growth_fwd,
                "eps_growth_fwd_pct": eps_growth_fwd,
                "rev_cagr_3y_pct": rev_cagr_3y,
            },
            "multiples": {
                "current": {"pe": cur_pe, "ps": cur_ps, "ev_ebitda": cur_ev_ebitda, "p_fcf": cur_pfcf},
                "peer_median": {"pe": peer_pe_med, "ps": peer_ps_med, "ev_ebitda": peer_ev_ebitda_med, "p_fcf": peer_pfcf_med},
                "premium_pct": {
                    "pe": _prem(cur_pe, peer_pe_med),
                    "ps": _prem(cur_ps, peer_ps_med),
                    "ev_ebitda": _prem(cur_ev_ebitda, peer_ev_ebitda_med),
                    "p_fcf": _prem(cur_pfcf, peer_pfcf_med),
                },
            },
            "fair_value": {
                "pe_based": pe_fv,
                "ps_based": ps_fv,
                "dcf_simplified": dcf_fv,
                "analyst_target": analyst_fv,
                "blended": blended_fv,
                "upside_pct": upside_pct,
            },
            "quality": {
                "roe": roe,
                "net_margin": net_margin,
                "debt_equity": de_ratio,
                "score": quality_score,
            },
            "summary": {
                "rating": rating,
                "confidence": confidence,
                "key_drivers": key_drivers,
            },
        }

        _warnings = []
        if not income_list:
            _warnings.append("income statement unavailable")
        if not balance:
            _warnings.append("balance sheet unavailable")
        if not cashflow:
            _warnings.append("cash flow unavailable")
        if not estimates_list:
            _warnings.append("analyst estimates unavailable")
        if not peer_symbols:
            _warnings.append("peer data unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result

    # ================================================================
    # 5. earnings_postmortem — "What just happened in earnings?"
    # ================================================================

    @mcp.tool(
        annotations={"title": "Earnings Postmortem", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
    )
    async def earnings_postmortem(symbol: str, quarter: int | None = None, year: int | None = None) -> dict:
        """Post-earnings synthesis: beat/miss, trend comparison, analyst reaction, market response, and guidance tone.

        Analyzes the most recent (or specified) earnings report. Returns EPS
        and revenue surprise, YoY/QoQ comparisons, post-earnings price reaction,
        analyst rating changes since the print, and guidance tone from transcript.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            quarter: Specific quarter (1-4) to analyze. Omit for most recent.
            year: Specific year to analyze. Omit for most recent.
        """
        symbol = symbol.upper().strip()
        sym = {"symbol": symbol}

        (
            earnings_data, income_data, grades_data,
            targets_data, history_data, quote_data,
            transcript_dates_data,
        ) = await asyncio.gather(
            client.get_safe("/stable/earnings", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/income-statement", params={**sym, "period": "quarter", "limit": 8}, cache_ttl=client.TTL_HOURLY, default=[]),
            client.get_safe("/stable/grades", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/price-target-consensus", params=sym, cache_ttl=client.TTL_6H, default=[]),
            client.get_safe("/stable/historical-price-eod/full", params={**sym, "from": (date.today() - timedelta(days=90)).isoformat(), "to": date.today().isoformat()}, cache_ttl=client.TTL_12H, default=[]),
            client.get_safe("/stable/quote", params=sym, cache_ttl=client.TTL_REALTIME, default=[]),
            client.get_safe("/stable/earning-call-transcript-dates", params=sym, cache_ttl=client.TTL_DAILY, default=[]),
        )

        earnings_list = earnings_data if isinstance(earnings_data, list) else []
        income_list = income_data if isinstance(income_data, list) else []
        grades_list = grades_data if isinstance(grades_data, list) else []
        targets = _safe_first(targets_data)
        historical = history_data if isinstance(history_data, list) else []
        quote = _safe_first(quote_data)
        transcript_dates = transcript_dates_data if isinstance(transcript_dates_data, list) else []

        if not earnings_list:
            return {"error": f"No earnings data found for '{symbol}'"}

        # Find the target earnings report
        today_str = date.today().isoformat()
        actual_earnings = [e for e in earnings_list if e.get("eps") is not None and (e.get("date") or "") <= today_str]
        actual_earnings.sort(key=lambda e: e.get("date", ""), reverse=True)

        target_report = None
        if quarter is not None and year is not None:
            # Find specific quarter
            for e in actual_earnings:
                fiscal_end = e.get("fiscalDateEnding", "")
                try:
                    fd = datetime.strptime(fiscal_end, "%Y-%m-%d").date()
                    fiscal_q = (fd.month - 1) // 3 + 1
                    fiscal_y = fd.year
                    if fiscal_q == quarter and fiscal_y == year:
                        target_report = e
                        break
                except (ValueError, TypeError):
                    continue
        if target_report is None:
            target_report = actual_earnings[0] if actual_earnings else None

        if not target_report:
            return {"error": f"No completed earnings found for '{symbol}'"}

        earnings_date = target_report.get("date", "")
        actual_eps = target_report.get("eps")
        est_eps = target_report.get("epsEstimated")
        actual_rev = target_report.get("revenue")
        est_rev = target_report.get("revenueEstimated")

        # Surprises
        eps_surprise = round((actual_eps - est_eps) / abs(est_eps) * 100, 2) if actual_eps is not None and est_eps and est_eps != 0 else None
        rev_surprise = round((actual_rev - est_rev) / abs(est_rev) * 100, 2) if actual_rev is not None and est_rev and est_rev != 0 else None
        beat = (actual_eps or 0) > (est_eps or 0) if actual_eps is not None and est_eps is not None else None

        # YoY and QoQ from income statements
        income_list.sort(key=lambda i: i.get("date", ""), reverse=True)

        # Find matching quarter in income statements by date proximity
        target_fiscal = target_report.get("fiscalDateEnding", "")
        current_q = None
        for i, inc in enumerate(income_list):
            if inc.get("date") == target_fiscal or (target_fiscal and inc.get("date", "")[:7] == target_fiscal[:7]):
                current_q = i
                break
        if current_q is None and income_list:
            current_q = 0  # fallback to latest

        yoy, qoq = {}, {}
        if current_q is not None:
            cq = income_list[current_q]
            # YoY = same quarter last year (4 quarters back)
            if current_q + 4 < len(income_list):
                yq = income_list[current_q + 4]
                yoy["revenue_growth_pct"] = _pct_change(cq.get("revenue"), yq.get("revenue"))
                yoy["earnings_growth_pct"] = _pct_change(cq.get("netIncome"), yq.get("netIncome"))
                # Margin delta in bps
                cur_gm = (cq.get("grossProfit") or 0) / cq["revenue"] if cq.get("revenue") else None
                prev_gm = (yq.get("grossProfit") or 0) / yq["revenue"] if yq.get("revenue") else None
                if cur_gm is not None and prev_gm is not None:
                    yoy["gross_margin_delta_bps"] = round((cur_gm - prev_gm) * 10000)
                cur_om = (cq.get("operatingIncome") or 0) / cq["revenue"] if cq.get("revenue") else None
                prev_om = (yq.get("operatingIncome") or 0) / yq["revenue"] if yq.get("revenue") else None
                if cur_om is not None and prev_om is not None:
                    yoy["op_margin_delta_bps"] = round((cur_om - prev_om) * 10000)

            # QoQ = prior quarter (1 quarter back)
            if current_q + 1 < len(income_list):
                pq = income_list[current_q + 1]
                qoq["revenue_growth_pct"] = _pct_change(cq.get("revenue"), pq.get("revenue"))
                qoq["earnings_growth_pct"] = _pct_change(cq.get("netIncome"), pq.get("netIncome"))

        # Post-earnings price reaction
        day_of_pct = None
        post_5d_pct = None
        if earnings_date and historical:
            # Find the earnings date and day after in history
            hist_by_date = {h.get("date"): h for h in historical}
            # Day of = close on earnings date vs previous close
            dates_sorted = sorted(hist_by_date.keys())
            ed_idx = None
            for i, d in enumerate(dates_sorted):
                if d and d >= earnings_date:
                    ed_idx = i
                    break

            if ed_idx is not None and ed_idx > 0:
                ed_close = hist_by_date[dates_sorted[ed_idx]].get("close")
                prev_close = hist_by_date[dates_sorted[ed_idx - 1]].get("close")
                day_of_pct = _pct_change(ed_close, prev_close)

                # 5d post
                if ed_idx + 5 <= len(dates_sorted):
                    post5_close = hist_by_date[dates_sorted[min(ed_idx + 5, len(dates_sorted) - 1)]].get("close")
                    post_5d_pct = _pct_change(post5_close, prev_close)

        # Reaction quality
        reaction_quality = None
        if eps_surprise is not None and day_of_pct is not None:
            if abs(day_of_pct) > abs(eps_surprise) * 0.5:
                reaction_quality = "strong"
            elif abs(day_of_pct) < abs(eps_surprise) * 0.2:
                reaction_quality = "muted"
            elif (eps_surprise > 0 and day_of_pct < 0) or (eps_surprise < 0 and day_of_pct > 0):
                reaction_quality = "inverse"
            else:
                reaction_quality = "proportional"

        # Analyst reaction post-print
        post_grades = [g for g in grades_list if (g.get("date") or "") >= earnings_date]
        upgrades_since = len([g for g in post_grades if (g.get("action") or "").lower() in ("upgrade", "initiate")])
        downgrades_since = len([g for g in post_grades if (g.get("action") or "").lower() == "downgrade"])
        recent_analyst = []
        for g in post_grades[:5]:
            recent_analyst.append({
                "firm": g.get("gradingCompany"),
                "action": g.get("action"),
                "new_grade": g.get("newGrade"),
                "date": g.get("date"),
            })

        # Guidance tone from transcript (if available)
        guidance = {"has_transcript": False, "tone": None, "snippet": None}
        # Check if transcript exists for this quarter
        fiscal_end = target_report.get("fiscalDateEnding", "")
        transcript_year = None
        transcript_quarter = None
        if fiscal_end:
            try:
                fd = datetime.strptime(fiscal_end, "%Y-%m-%d").date()
                transcript_quarter = (fd.month - 1) // 3 + 1
                transcript_year = fd.year
            except (ValueError, TypeError):
                pass

        if transcript_year and transcript_quarter:
            # Check if we have a matching transcript date
            has_transcript = any(
                (t.get("fiscalYear") == transcript_year and t.get("quarter") == transcript_quarter)
                for t in transcript_dates
            )
            if has_transcript:
                transcript_data = await client.get_safe(
                    "/stable/earning-call-transcript",
                    params={"symbol": symbol, "year": transcript_year, "quarter": transcript_quarter},
                    cache_ttl=client.TTL_DAILY,
                    default=[],
                )
                transcript_list = transcript_data if isinstance(transcript_data, list) else []
                if transcript_list:
                    content = " ".join(t.get("content", "") for t in transcript_list)
                    guidance["has_transcript"] = True
                    # Simple sentiment scan
                    content_lower = content.lower()
                    positive_kw = ["strong", "growth", "record", "accelerat", "momentum", "confident", "optimistic", "exceed", "above expectations"]
                    negative_kw = ["headwind", "challenge", "decline", "soft", "pressure", "cautious", "uncertain", "below expectations", "weakness"]
                    pos_count = sum(1 for kw in positive_kw if kw in content_lower)
                    neg_count = sum(1 for kw in negative_kw if kw in content_lower)
                    if pos_count > neg_count * 1.5:
                        guidance["tone"] = "positive"
                    elif neg_count > pos_count * 1.5:
                        guidance["tone"] = "negative"
                    else:
                        guidance["tone"] = "mixed"
                    # Snippet: first 300 chars
                    guidance["snippet"] = content[:300] if content else None

        # Summary
        headline_parts = []
        if beat is True:
            headline_parts.append(f"beat by {eps_surprise:.1f}%" if eps_surprise else "EPS beat")
        elif beat is False:
            headline_parts.append(f"missed by {abs(eps_surprise or 0):.1f}%")
        if rev_surprise is not None:
            headline_parts.append(f"rev {'beat' if rev_surprise > 0 else 'miss'} {abs(rev_surprise):.1f}%")
        headline = ", ".join(headline_parts) if headline_parts else "results reported"

        beat_quality = "solid" if (eps_surprise or 0) > 5 and (rev_surprise or 0) > 2 else "narrow" if beat else "miss"

        key_positives = []
        key_concerns = []
        if (eps_surprise or 0) > 0:
            key_positives.append(f"EPS beat +{eps_surprise:.1f}%")
        if (rev_surprise or 0) > 0:
            key_positives.append(f"revenue beat +{rev_surprise:.1f}%")
        if yoy.get("revenue_growth_pct") and yoy["revenue_growth_pct"] > 0:
            key_positives.append(f"YoY revenue +{yoy['revenue_growth_pct']:.1f}%")
        if upgrades_since > downgrades_since:
            key_positives.append(f"{upgrades_since} analyst upgrades since report")
        if guidance.get("tone") == "positive":
            key_positives.append("positive guidance tone")

        if (eps_surprise or 0) < 0:
            key_concerns.append(f"EPS miss {eps_surprise:.1f}%")
        if (rev_surprise or 0) < 0:
            key_concerns.append(f"revenue miss {rev_surprise:.1f}%")
        if downgrades_since > upgrades_since:
            key_concerns.append(f"{downgrades_since} analyst downgrades since report")
        if guidance.get("tone") == "negative":
            key_concerns.append("negative guidance tone")

        result = {
            "symbol": symbol,
            "earnings_date": earnings_date,
            "results": {
                "actual_eps": actual_eps,
                "est_eps": est_eps,
                "surprise_pct": eps_surprise,
                "actual_rev": actual_rev,
                "est_rev": est_rev,
                "rev_surprise_pct": rev_surprise,
                "beat": beat,
            },
            "yoy": yoy,
            "qoq": qoq,
            "guidance": guidance,
            "analyst_reaction": {
                "upgrades_since": upgrades_since,
                "downgrades_since": downgrades_since,
                "recent_actions": recent_analyst,
            },
            "market_reaction": {
                "day_of_pct": day_of_pct,
                "post_5d_pct": post_5d_pct,
                "reaction_quality": reaction_quality,
            },
            "summary": {
                "headline": headline,
                "beat_quality": beat_quality,
                "key_positives": key_positives,
                "key_concerns": key_concerns,
            },
        }

        _warnings = []
        if not earnings_list:
            _warnings.append("earnings data unavailable")
        if not income_list:
            _warnings.append("income statement unavailable")
        if not grades_list:
            _warnings.append("analyst grades unavailable")
        if not historical:
            _warnings.append("historical prices unavailable")
        if _warnings:
            result["_warnings"] = _warnings

        return result
