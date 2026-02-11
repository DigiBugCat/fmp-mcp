"""Async FMP API client with TTL caching and error handling."""

from __future__ import annotations

import time
from typing import Any

import httpx


class FMPError(Exception):
    """Raised when the FMP API returns an error."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class FMPClient:
    """Async HTTP client for Financial Modeling Prep API.

    Features:
    - Simple in-memory TTL cache
    - Graceful error handling for composite tools
    - Automatic API key injection
    """

    BASE_URL = "https://financialmodelingprep.com"

    # Default cache TTLs by data type
    TTL_REALTIME = 60  # Quotes, prices
    TTL_HOURLY = 3600  # Financial statements
    TTL_6H = 21600  # Analyst data
    TTL_12H = 43200  # Historical prices
    TTL_DAILY = 86400  # Profiles, rarely changing data

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )
        self._cache: dict[str, tuple[float, Any]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _cache_key(self, path: str, params: dict | None) -> str:
        sorted_params = sorted((params or {}).items())
        return f"{path}?{'&'.join(f'{k}={v}' for k, v in sorted_params)}"

    async def get(
        self,
        path: str,
        params: dict | None = None,
        cache_ttl: int = 300,
    ) -> Any:
        """Make a GET request to the FMP API.

        Args:
            path: API path (e.g. "/api/v3/profile/AAPL")
            params: Additional query parameters
            cache_ttl: Cache duration in seconds (0 to disable)

        Returns:
            Parsed JSON response

        Raises:
            FMPError: On API errors or invalid responses
        """
        params = dict(params or {})
        params["apikey"] = self.api_key

        key = self._cache_key(path, params)

        # Check cache
        if cache_ttl > 0 and key in self._cache:
            cached_at, data = self._cache[key]
            if time.monotonic() - cached_at < cache_ttl:
                return data

        try:
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FMPError(
                f"FMP API error {e.response.status_code}: {e.response.text[:200]}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise FMPError(f"Request failed: {e}") from e

        data = resp.json()

        # FMP returns {"Error Message": "..."} on some errors
        if isinstance(data, dict) and "Error Message" in data:
            raise FMPError(data["Error Message"])

        # Cache the result
        if cache_ttl > 0:
            self._cache[key] = (time.monotonic(), data)

        return data

    async def get_safe(
        self,
        path: str,
        params: dict | None = None,
        cache_ttl: int = 300,
        default: Any = None,
    ) -> Any:
        """Like get() but returns default on error instead of raising.

        Used in composite tools where partial data is better than failure.
        """
        try:
            return await self.get(path, params=params, cache_ttl=cache_ttl)
        except FMPError:
            return default
