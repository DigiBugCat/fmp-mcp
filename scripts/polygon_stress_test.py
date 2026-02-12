"""Stress test Polygon options OI endpoint to measure real throughput.

Usage:
    uv run python scripts/polygon_stress_test.py

Reads POLYGON_API_KEY from .env file. Tests various concurrency levels
against /v3/snapshot/options/{symbol} to see how fast we can fetch OI.
"""

import asyncio
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("POLYGON_API_KEY", "")
BASE = "https://api.polygon.io"

# Symbols to test — mix of mega-cap, large-cap, mid-cap
TEST_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "MA", "HD", "PG", "COST",
    "ABBV", "CRM", "NFLX", "AMD", "PEP",
    "TMO", "ADBE", "CSCO", "QCOM", "INTC",
    "CMCSA", "TXN", "AMGN", "HON", "LOW",
]


async def fetch_oi(client: httpx.AsyncClient, symbol: str, sem: asyncio.Semaphore) -> dict:
    """Fetch options OI for a single symbol."""
    async with sem:
        start = time.monotonic()
        try:
            resp = await client.get(
                f"/v3/snapshot/options/{symbol}",
                params={"apiKey": API_KEY, "limit": 250},
            )
            elapsed = time.monotonic() - start
            if resp.status_code == 429:
                return {"symbol": symbol, "status": "RATE_LIMITED", "elapsed": elapsed}
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            total_oi = sum(c.get("open_interest", 0) for c in results)
            call_oi = sum(
                c.get("open_interest", 0) for c in results
                if (c.get("details") or {}).get("contract_type") == "call"
            )
            put_oi = sum(
                c.get("open_interest", 0) for c in results
                if (c.get("details") or {}).get("contract_type") == "put"
            )
            return {
                "symbol": symbol,
                "status": "OK",
                "elapsed": elapsed,
                "contracts": len(results),
                "total_oi": total_oi,
                "call_oi": call_oi,
                "put_oi": put_oi,
            }
        except Exception as e:
            elapsed = time.monotonic() - start
            return {"symbol": symbol, "status": f"ERROR: {e}", "elapsed": elapsed}


async def run_test(symbols: list[str], concurrency: int) -> dict:
    """Run a batch of OI fetches at a given concurrency level."""
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        start = time.monotonic()
        results = await asyncio.gather(*[fetch_oi(client, s, sem) for s in symbols])
        wall_time = time.monotonic() - start

    ok = [r for r in results if r["status"] == "OK"]
    rate_limited = [r for r in results if r["status"] == "RATE_LIMITED"]
    errors = [r for r in results if r["status"] not in ("OK", "RATE_LIMITED")]

    avg_latency = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0

    return {
        "concurrency": concurrency,
        "total_symbols": len(symbols),
        "wall_time": round(wall_time, 2),
        "ok": len(ok),
        "rate_limited": len(rate_limited),
        "errors": len(errors),
        "avg_latency_ms": round(avg_latency * 1000),
        "throughput_rps": round(len(ok) / wall_time, 1) if wall_time > 0 else 0,
        "results": results,
    }


async def main():
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not set in .env")
        return

    print(f"Polygon Options OI Stress Test")
    print(f"Symbols: {len(TEST_SYMBOLS)}")
    print(f"Endpoint: /v3/snapshot/options/{{symbol}}?limit=250")
    print("=" * 70)

    # Test sequential first (baseline)
    print("\n--- Sequential (concurrency=1) ---")
    # Just test 5 symbols sequentially to get baseline latency
    result = await run_test(TEST_SYMBOLS[:5], concurrency=1)
    print(f"  Wall time: {result['wall_time']}s for {result['total_symbols']} symbols")
    print(f"  OK: {result['ok']}, Rate limited: {result['rate_limited']}, Errors: {result['errors']}")
    print(f"  Avg latency: {result['avg_latency_ms']}ms")
    print(f"  Throughput: {result['throughput_rps']} req/s")
    for r in result["results"]:
        status = r["status"]
        if status == "OK":
            print(f"    {r['symbol']}: {r['elapsed']*1000:.0f}ms, {r['contracts']} contracts, OI={r['total_oi']:,}")
        else:
            print(f"    {r['symbol']}: {status} ({r['elapsed']*1000:.0f}ms)")

    # Now test increasing concurrency
    for conc in [5, 10, 20]:
        print(f"\n--- Concurrency={conc}, {len(TEST_SYMBOLS)} symbols ---")
        result = await run_test(TEST_SYMBOLS, concurrency=conc)
        print(f"  Wall time: {result['wall_time']}s")
        print(f"  OK: {result['ok']}, Rate limited: {result['rate_limited']}, Errors: {result['errors']}")
        print(f"  Avg latency: {result['avg_latency_ms']}ms")
        print(f"  Throughput: {result['throughput_rps']} req/s")

        if result["rate_limited"]:
            rl_symbols = [r["symbol"] for r in result["results"] if r["status"] == "RATE_LIMITED"]
            print(f"  Rate-limited symbols: {rl_symbols}")

        # Print per-symbol OI for the first test
        if conc == 5:
            print("  Per-symbol results:")
            for r in sorted(result["results"], key=lambda x: -(x.get("total_oi") or 0)):
                if r["status"] == "OK":
                    pcr = round(r["put_oi"] / r["call_oi"], 2) if r["call_oi"] > 0 else "N/A"
                    print(f"    {r['symbol']:6s}: OI={r['total_oi']:>10,}  (C={r['call_oi']:,} P={r['put_oi']:,} P/C={pcr})  {r['contracts']} contracts  {r['elapsed']*1000:.0f}ms")
                else:
                    print(f"    {r['symbol']:6s}: {r['status']}")

    print("\n" + "=" * 70)
    print("Done. Use these results to set POLYGON_MIN_INTERVAL in .env")


if __name__ == "__main__":
    asyncio.run(main())
