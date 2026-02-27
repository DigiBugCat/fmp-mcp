# FMP Docs Parity Checklist

Source docs: https://site.financialmodelingprep.com/developer/docs

This checklist tracks parity at **endpoint family** level (not every single endpoint variant).
For the latest machine-readable gap report, call MCP tool:

- `fmp_coverage_gaps`
- `fmp_coverage_gaps(include_implemented_categories=true)`

## Coverage Model
- Implemented coverage is sourced from the static endpoint-family registry in `tools/_endpoint_registry.py` (used by the `fmp_coverage_gaps` meta tool).
- Docs parity is mapped to curated endpoint families by category.
- Non-REST capabilities such as WebSocket are tracked as category-level gaps.

## Current Focus
- Keep high-value market/financial workflows covered first.
- Use `fmp_coverage_gaps` to identify missing families before adding new tools.

## Categories
- Covered or mostly covered:
  - Profile & company data
  - Quote and price history
  - Financial statements and ratios
  - Estimates and ratings
  - Ownership (institutional/insider/float)
  - ETF lookups
  - Macro, market breadth, calendars
  - News and M&A
  - Commodity/crypto/forex quotes

- Known missing/partial gaps to evaluate next:
  - `esg`
  - `commitment-of-traders`
  - `fundraisers`
  - `bulk`
  - `websocket`

## Agent Usage Pattern
1. Call `fmp_coverage_gaps`.
2. Check `unimplemented_families` for capability gaps.
3. If needed, prioritize additions by user value and data reliability.
4. Add a new MCP tool only when the gap is materially useful for research workflows.
