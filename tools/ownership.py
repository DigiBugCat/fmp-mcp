"""Insider activity and institutional ownership tools (Tier 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fmp_client import FMPClient


def register(mcp: FastMCP, client: FMPClient) -> None:
    """Tier 2 tools - to be implemented after MVP validation."""
    pass
