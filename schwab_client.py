"""Async Schwab backend API client with TTL caching and error handling."""

from __future__ import annotations

import time
from typing import Any

import httpx


class SchwabError(Exception):
    """Raised when the Schwab backend returns an error."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class SchwabClient:
    """Async HTTP client for the Schwab backend REST API.

    Features:
    - Simple in-memory TTL cache (mirrors PolygonClient)
    - Graceful error handling for composite tools
    - Cloudflare Access service token injection
    """

    # Cache TTLs
    TTL_REALTIME = 60
    TTL_HOURLY = 3600
    TTL_6H = 21600
    TTL_DAILY = 86400

    def __init__(
        self,
        base_url: str,
        cf_access_client_id: str = "",
        cf_access_client_secret: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self._cf_access_client_id = cf_access_client_id
        self._cf_access_client_secret = cf_access_client_secret
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"Accept": "application/json"}
            if self._cf_access_client_id and self._cf_access_client_secret:
                headers["CF-Access-Client-Id"] = self._cf_access_client_id
                headers["CF-Access-Client-Secret"] = self._cf_access_client_secret
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _cache_key(self, method: str, path: str, params: dict | None, body: dict | None) -> str:
        sorted_params = sorted((params or {}).items())
        sorted_body = sorted((body or {}).items())
        return f"{method}:{path}?{'&'.join(f'{k}={v}' for k, v in sorted_params)}|{'&'.join(f'{k}={v}' for k, v in sorted_body)}"

    async def get(
        self,
        path: str,
        params: dict | None = None,
        cache_ttl: int = 60,
    ) -> Any:
        """Make a GET request to the Schwab backend.

        Args:
            path: API path (e.g. "/quotes/AAPL")
            params: Additional query parameters
            cache_ttl: Cache duration in seconds (0 to disable)

        Returns:
            Parsed JSON response

        Raises:
            SchwabError: On API errors or invalid responses
        """
        key = self._cache_key("GET", path, params, None)

        if cache_ttl > 0 and key in self._cache:
            cached_at, data = self._cache[key]
            if time.monotonic() - cached_at < cache_ttl:
                return data

        try:
            resp = await self._get_client().get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise SchwabError(
                f"Schwab backend error {e.response.status_code}: {e.response.text[:200]}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise SchwabError(f"Request failed: {e}") from e

        data = resp.json()

        if cache_ttl > 0:
            self._cache[key] = (time.monotonic(), data)

        return data

    async def get_safe(
        self,
        path: str,
        params: dict | None = None,
        cache_ttl: int = 60,
        default: Any = None,
    ) -> Any:
        """Like get() but returns default on error instead of raising."""
        try:
            return await self.get(path, params=params, cache_ttl=cache_ttl)
        except SchwabError:
            return default

    async def post(
        self,
        path: str,
        body: dict | None = None,
        cache_ttl: int = 60,
    ) -> Any:
        """Make a POST request to the Schwab backend.

        Args:
            path: API path (e.g. "/schwab/call")
            body: JSON request body
            cache_ttl: Cache duration in seconds (0 to disable)

        Returns:
            Parsed JSON response

        Raises:
            SchwabError: On API errors or invalid responses
        """
        key = self._cache_key("POST", path, None, body)

        if cache_ttl > 0 and key in self._cache:
            cached_at, data = self._cache[key]
            if time.monotonic() - cached_at < cache_ttl:
                return data

        try:
            resp = await self._get_client().post(path, json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise SchwabError(
                f"Schwab backend error {e.response.status_code}: {e.response.text[:200]}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise SchwabError(f"Request failed: {e}") from e

        data = resp.json()

        if cache_ttl > 0:
            self._cache[key] = (time.monotonic(), data)

        return data

    async def post_safe(
        self,
        path: str,
        body: dict | None = None,
        cache_ttl: int = 60,
        default: Any = None,
    ) -> Any:
        """Like post() but returns default on error instead of raising."""
        try:
            return await self.post(path, body=body, cache_ttl=cache_ttl)
        except SchwabError:
            return default

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def get_quote(self, symbol: str) -> dict | None:
        """Get a real-time quote from the Schwab backend.

        Returns the formatted quote dict, or None on failure.
        """
        return await self.get_safe(f"/quotes/{symbol}", cache_ttl=self.TTL_REALTIME)

    async def get_option_chain(self, symbol: str, **kwargs: Any) -> dict | None:
        """Get option chain from the Schwab backend via the generic call endpoint.

        Returns the raw Schwab option chain response, or None on failure.
        """
        body = {
            "method_name": "get_option_chain",
            "args": [symbol],
            "kwargs": kwargs,
        }
        result = await self.post_safe("/schwab/call", body=body, cache_ttl=self.TTL_REALTIME)
        if result and isinstance(result, dict):
            return result.get("result", result)
        return None
