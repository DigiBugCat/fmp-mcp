"""Earnings call transcript tools."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def register(mcp: FastMCP, client: FMPClient) -> None:
    @mcp.tool(
        annotations={
            "title": "Earnings Transcript",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def earnings_transcript(
        symbol: str,
        year: int | str | None = None,
        quarter: int | str | None = None,
        latest_expected: bool = False,
        max_chars: int | str = 100000,
        offset: int | str = 0,
    ) -> dict:
        """Get an earnings call transcript for a company.

        When year/quarter are not specified, fetches the most recent available
        transcript. Returns paginated transcript content with line-boundary
        snapping. Use offset + max_chars to paginate through long transcripts.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            year: Fiscal year (e.g. 2025). If quarter omitted, returns latest
                available quarter in that fiscal year.
            quarter: Quarter number 1-4. If year omitted, returns latest
                available fiscal year for that quarter.
            latest_expected: If true (and no year/quarter filters are passed),
                checks whether a newer completed earnings report exists than
                the latest available transcript and flags potential posting lag.
            max_chars: Max characters to return per call (default 100000)
            offset: Character offset to start from (default 0). Use next_offset from previous response to continue.
        """
        symbol = symbol.upper().strip()

        # Coerce string inputs (MCP clients may send strings)
        def _to_int(v: int | str | None) -> int | None:
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        year = _to_int(year)
        quarter = _to_int(quarter)
        max_chars = _to_int(max_chars) or 100000
        offset = _to_int(offset) or 0

        requested_year = year
        requested_quarter = quarter

        if quarter is not None and quarter not in (1, 2, 3, 4):
            return {"error": f"Invalid quarter '{quarter}'. Must be 1, 2, 3, or 4."}

        if year is not None and quarter is not None:
            # Direct fetch for specific quarter
            transcript_data = await client.get_safe(
                "/stable/earning-call-transcript",
                params={"symbol": symbol, "year": year, "quarter": quarter},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            )
        else:
            # Find available dates first, then fetch latest matching period filter.
            # Keep this fresh to pick up newly posted transcripts around earnings day.
            dates_data = await client.get_safe(
                "/stable/earning-call-transcript-dates",
                params={"symbol": symbol},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            )

            dates_list = dates_data if isinstance(dates_data, list) else []

            if not dates_list:
                return {"error": f"No earnings transcripts available for '{symbol}'"}

            # dates_list contains objects with fiscalYear/quarter.
            # Filter by optional year/quarter, then pick most recent match.
            filtered_dates: list[tuple[int, int]] = []
            for d in dates_list:
                y_raw = d.get("fiscalYear") or d.get("year")
                q_raw = d.get("quarter")
                if y_raw is None or q_raw is None:
                    continue
                try:
                    y = int(y_raw)
                    q = int(q_raw)
                except (TypeError, ValueError):
                    continue
                if year is not None and y != year:
                    continue
                if quarter is not None and q != quarter:
                    continue
                filtered_dates.append((y, q))

            if not filtered_dates:
                filters = []
                if year is not None:
                    filters.append(f"year={year}")
                if quarter is not None:
                    filters.append(f"quarter={quarter}")
                if filters:
                    return {"error": f"No earnings transcripts available for '{symbol}' matching {', '.join(filters)}"}
                return {"error": f"No valid transcript dates found for '{symbol}'"}

            filtered_dates.sort(reverse=True)
            target_year, target_quarter = filtered_dates[0]

            year = target_year
            quarter = target_quarter

            transcript_data = await client.get_safe(
                "/stable/earning-call-transcript",
                params={"symbol": symbol, "year": target_year, "quarter": target_quarter},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            )

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

        total_chars = len(transcript_text)

        # Clamp offset
        offset = max(0, min(offset, total_chars))
        max_chars = max(1, max_chars)

        # Snap offset forward to next line boundary (unless 0 or already at one)
        start = offset
        if start > 0 and start < total_chars and transcript_text[start - 1] != "\n":
            nl = transcript_text.find("\n", start)
            start = nl + 1 if nl != -1 else start

        # Compute end and snap backward to line boundary
        end = min(start + max_chars, total_chars)
        if end < total_chars:
            nl = transcript_text.rfind("\n", start, end)
            if nl != -1 and nl > start:
                end = nl + 1

        chunk = transcript_text[start:end]
        truncated = end < total_chars

        result = {
            "symbol": symbol,
            "year": year,
            "quarter": quarter,
            "date": transcript_list[0].get("date") if transcript_list else None,
            "content": chunk,
            "length_chars": len(chunk),
            "total_chars": total_chars,
            "offset": start,
            "truncated": truncated,
        }
        if truncated:
            result["next_offset"] = end
            result["_warnings"] = [
                f"Transcript truncated ({len(chunk)}/{total_chars} chars shown). "
                f"Call again with offset={end} to continue reading."
            ]

        if latest_expected and requested_year is None and requested_quarter is None:
            latest_completed_earnings_date = None
            earnings_data = await client.get_safe(
                "/stable/earnings",
                params={"symbol": symbol},
                cache_ttl=client.TTL_REALTIME,
                default=[],
            )
            earnings_list = earnings_data if isinstance(earnings_data, list) else []
            today_str = date.today().isoformat()
            completed = [
                e for e in earnings_list
                if e.get("epsActual") is not None and (e.get("date") or "") <= today_str
            ]
            if completed:
                completed.sort(key=lambda e: e.get("date", ""), reverse=True)
                latest_completed_earnings_date = completed[0].get("date")

            transcript_date = result.get("date")
            met = True
            if latest_completed_earnings_date and transcript_date:
                met = latest_completed_earnings_date <= transcript_date

            result["latest_expected"] = True
            result["latest_expected_met"] = met
            if latest_completed_earnings_date:
                result["latest_completed_earnings_date"] = latest_completed_earnings_date

            if not met:
                warnings = result.get("_warnings", [])
                warnings.append(
                    "Latest completed earnings appears newer than available transcript; "
                    "the new transcript may not be posted yet."
                )
                result["_warnings"] = warnings

        return result
