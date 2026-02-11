"""Earnings call transcript tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Earnings Transcript",
            "readOnlyHint": True,
        }
    )
    async def earnings_transcript(
        symbol: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Get an earnings call transcript for a company.

        When year/quarter are not specified, fetches the most recent available
        transcript. Returns the full transcript text.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            year: Fiscal year (e.g. 2025). Omit for latest available.
            quarter: Quarter number 1-4. Omit for latest available.
        """
        symbol = symbol.upper().strip()

        if year is not None and quarter is not None:
            # Direct fetch for specific quarter
            transcript_data = await client.get_safe(
                "/stable/earning-call-transcript",
                params={"symbol": symbol, "year": year, "quarter": quarter},
                cache_ttl=client.TTL_DAILY,
                default=[],
            )
        else:
            # Find available dates first, then fetch latest
            dates_data = await client.get_safe(
                "/stable/earning-call-transcript-dates",
                params={"symbol": symbol},
                cache_ttl=client.TTL_DAILY,
                default=[],
            )

            dates_list = dates_data if isinstance(dates_data, list) else []

            if not dates_list:
                return {"error": f"No earnings transcripts available for '{symbol}'"}

            # dates_list contains objects with year/quarter; pick the latest
            # Sort by year desc, quarter desc to get most recent
            dates_list.sort(
                key=lambda d: (d.get("year", 0), d.get("quarter", 0)),
                reverse=True,
            )
            latest = dates_list[0]
            target_year = latest.get("year")
            target_quarter = latest.get("quarter")

            if target_year is None or target_quarter is None:
                return {"error": f"No valid transcript dates found for '{symbol}'"}

            transcript_data = await client.get_safe(
                "/stable/earning-call-transcript",
                params={"symbol": symbol, "year": target_year, "quarter": target_quarter},
                cache_ttl=client.TTL_DAILY,
                default=[],
            )
            year = target_year
            quarter = target_quarter

        transcript_list = transcript_data if isinstance(transcript_data, list) else []

        if not transcript_list:
            return {"error": f"No transcript found for '{symbol}' Q{quarter} {year}"}

        # Transcript endpoint returns a list; concatenate all content
        full_content = []
        for segment in transcript_list:
            content = segment.get("content") or ""
            if content:
                full_content.append(content)

        transcript_text = "\n\n".join(full_content)

        if not transcript_text:
            return {"error": f"Transcript for '{symbol}' Q{quarter} {year} is empty"}

        result = {
            "symbol": symbol,
            "year": year,
            "quarter": quarter,
            "date": transcript_list[0].get("date") if transcript_list else None,
            "content": transcript_text,
            "length_chars": len(transcript_text),
        }

        return result
