"""Shared test fixtures."""

from __future__ import annotations

import pytest
import respx

from fmp_client import FMPClient


@pytest.fixture
def fmp_client():
    """Create an FMPClient with a test API key."""
    return FMPClient(api_key="test_key")


@pytest.fixture
def mock_api():
    """Start respx mock for FMP API calls (FMPClient unit tests only)."""
    with respx.mock(base_url="https://financialmodelingprep.com", assert_all_called=False) as api:
        yield api


# --- Sample response data matching /stable/ API ---

AAPL_PROFILE = [{
    "symbol": "AAPL",
    "companyName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "ceo": "Mr. Timothy D. Cook",
    "fullTimeEmployees": "164000",
    "description": "Apple Inc. designs, manufactures, and markets smartphones...",
    "exchange": "NASDAQ",
    "country": "US",
    "website": "https://www.apple.com",
    "price": 273.68,
    "marketCap": 4022528102504,
    "beta": 1.107,
    "range": "169.21-288.62",
}]

AAPL_QUOTE = [{
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "price": 273.68,
    "changePercentage": -0.34,
    "change": -0.94,
    "volume": 34311675,
    "dayLow": 272.94,
    "dayHigh": 275.36,
    "yearHigh": 288.62,
    "yearLow": 169.21,
    "marketCap": 4022528102504,
    "priceAvg50": 268.66,
    "priceAvg200": 238.92,
    "exchange": "NASDAQ",
    "open": 274.885,
    "previousClose": 274.62,
    "timestamp": 1770757202,
}]

AAPL_RATIOS = [{
    "symbol": "AAPL",
    "grossProfitMarginTTM": 0.4733,
    "operatingProfitMarginTTM": 0.3238,
    "netProfitMarginTTM": 0.2704,
    "priceToEarningsRatioTTM": 34.27,
    "priceToEarningsGrowthRatioTTM": 5.83,
    "priceToBookRatioTTM": 45.77,
    "priceToSalesRatioTTM": 9.23,
    "priceToFreeCashFlowRatioTTM": 32.62,
    "enterpriseValueMultipleTTM": 27.5,
    "dividendYieldTTM": 0.005,
    "returnOnEquityTTM": 1.56,
    "returnOnAssetsTTM": 0.33,
    "debtToEquityRatioTTM": 1.03,
    "currentRatioTTM": 0.97,
}]

AAPL_INCOME = [
    {
        "date": "2025-09-27", "symbol": "AAPL", "period": "FY",
        "revenue": 416161000000, "grossProfit": 195201000000,
        "operatingIncome": 133050000000, "netIncome": 112010000000,
        "eps": 7.49, "epsDiluted": 7.46, "ebitda": 144427000000,
    },
    {
        "date": "2024-09-28", "symbol": "AAPL", "period": "FY",
        "revenue": 391035000000, "grossProfit": 180683000000,
        "operatingIncome": 123216000000, "netIncome": 93736000000,
        "eps": 6.08, "epsDiluted": 6.08, "ebitda": 134658000000,
    },
    {
        "date": "2023-09-30", "symbol": "AAPL", "period": "FY",
        "revenue": 383285000000, "grossProfit": 169148000000,
        "operatingIncome": 114301000000, "netIncome": 96995000000,
        "eps": 6.16, "epsDiluted": 6.13, "ebitda": 125820000000,
    },
    {
        "date": "2022-09-24", "symbol": "AAPL", "period": "FY",
        "revenue": 394328000000, "grossProfit": 170782000000,
        "operatingIncome": 119437000000, "netIncome": 99803000000,
        "eps": 6.15, "epsDiluted": 6.11, "ebitda": 130541000000,
    },
]

AAPL_BALANCE = [
    {"date": "2025-09-27", "symbol": "AAPL", "period": "FY", "totalAssets": 359241000000, "totalLiabilities": 285508000000, "totalStockholdersEquity": 73733000000, "totalDebt": 98657000000, "cashAndCashEquivalents": 35934000000, "netDebt": 62723000000},
    {"date": "2024-09-28", "symbol": "AAPL", "period": "FY", "totalAssets": 364980000000, "totalLiabilities": 308030000000, "totalStockholdersEquity": 56950000000, "totalDebt": 97300000000, "cashAndCashEquivalents": 29943000000, "netDebt": 49070000000},
    {"date": "2023-09-30", "symbol": "AAPL", "period": "FY", "totalAssets": 352583000000, "totalLiabilities": 290437000000, "totalStockholdersEquity": 62146000000, "totalDebt": 111088000000, "cashAndCashEquivalents": 29965000000, "netDebt": 81123000000},
    {"date": "2022-09-24", "symbol": "AAPL", "period": "FY", "totalAssets": 352755000000, "totalLiabilities": 302083000000, "totalStockholdersEquity": 50672000000, "totalDebt": 120069000000, "cashAndCashEquivalents": 23646000000, "netDebt": 96423000000},
]

AAPL_CASHFLOW = [
    {"date": "2025-09-27", "symbol": "AAPL", "period": "FY", "operatingCashFlow": 111482000000, "capitalExpenditure": -12715000000, "freeCashFlow": 98767000000, "commonDividendsPaid": -15421000000, "commonStockRepurchased": -90711000000},
    {"date": "2024-09-28", "symbol": "AAPL", "period": "FY", "operatingCashFlow": 118254000000, "capitalExpenditure": -9959000000, "freeCashFlow": 108295000000, "commonDividendsPaid": -15025000000, "commonStockRepurchased": -94949000000},
    {"date": "2023-09-30", "symbol": "AAPL", "period": "FY", "operatingCashFlow": 110543000000, "capitalExpenditure": -11052000000, "freeCashFlow": 99584000000, "commonDividendsPaid": -15025000000, "commonStockRepurchased": -77550000000},
    {"date": "2022-09-24", "symbol": "AAPL", "period": "FY", "operatingCashFlow": 122151000000, "capitalExpenditure": -10708000000, "freeCashFlow": 111443000000, "commonDividendsPaid": -14841000000, "commonStockRepurchased": -89402000000},
]

AAPL_PRICE_TARGET = [{
    "symbol": "AAPL",
    "targetConsensus": 303.11,
    "targetHigh": 350,
    "targetLow": 220,
    "targetMedian": 315,
}]

AAPL_GRADES = [{
    "symbol": "AAPL",
    "strongBuy": 1,
    "buy": 68,
    "hold": 33,
    "sell": 7,
    "strongSell": 0,
    "consensus": "Buy",
}]

AAPL_RATING = [{
    "symbol": "AAPL",
    "rating": "B",
    "overallScore": 3,
    "discountedCashFlowScore": 3,
    "returnOnEquityScore": 5,
    "returnOnAssetsScore": 5,
    "debtToEquityScore": 1,
    "priceToEarningsScore": 2,
    "priceToBookScore": 1,
}]

AAPL_SEARCH = [
    {"symbol": "APC.F", "name": "Apple Inc.", "currency": "EUR", "exchangeFullName": "Frankfurt", "exchange": "FSX"},
    {"symbol": "AAPL", "name": "Apple Inc.", "currency": "USD", "exchangeFullName": "NASDAQ Global Select", "exchange": "NASDAQ"},
]

AAPL_SCREENER = [
    {"symbol": "NVDA", "companyName": "NVIDIA Corporation", "marketCap": 4590383462958, "sector": "Technology", "industry": "Semiconductors", "price": 188.54, "exchangeShortName": "NASDAQ"},
    {"symbol": "AAPL", "companyName": "Apple Inc.", "marketCap": 4022528102504, "sector": "Technology", "industry": "Consumer Electronics", "price": 273.68, "exchangeShortName": "NASDAQ"},
]

# /stable/historical-price-eod/full returns flat list (not nested under "historical")
AAPL_HISTORICAL = [
    {"symbol": "AAPL", "date": "2025-02-11", "open": 228.2, "high": 235.23, "low": 228.13, "close": 232.62, "volume": 53718400},
    {"symbol": "AAPL", "date": "2025-02-10", "open": 227.0, "high": 229.5, "low": 226.5, "close": 228.50, "volume": 52000000},
    {"symbol": "AAPL", "date": "2025-02-07", "open": 226.0, "high": 228.0, "low": 225.5, "close": 227.20, "volume": 48000000},
] + [
    {"symbol": "AAPL", "date": f"2025-02-{6 - i:02d}" if 6 - i > 0 else f"2025-01-{31 + (6 - i):02d}",
     "close": 225.0 + i * 0.5, "volume": 50000000}
    for i in range(28)
]

AAPL_ANALYST_ESTIMATES = [
    {"symbol": "AAPL", "date": "2028-09-27", "revenueLow": 117592038224, "revenueHigh": 128328337770, "revenueAvg": 123401826658, "epsAvg": 2.45, "epsHigh": 2.58, "epsLow": 2.30, "numAnalystsRevenue": 8, "numAnalystsEps": 9, "ebitdaAvg": 42023491218},
    {"symbol": "AAPL", "date": "2028-06-27", "revenueLow": 98000000000, "revenueHigh": 110000000000, "revenueAvg": 105000000000, "epsAvg": 1.85, "epsHigh": 2.00, "epsLow": 1.72, "numAnalystsRevenue": 12, "numAnalystsEps": 14, "ebitdaAvg": 36000000000},
    {"symbol": "AAPL", "date": "2028-03-27", "revenueLow": 90000000000, "revenueHigh": 100000000000, "revenueAvg": 95000000000, "epsAvg": 1.62, "epsHigh": 1.75, "epsLow": 1.50, "numAnalystsRevenue": 15, "numAnalystsEps": 18, "ebitdaAvg": 33000000000},
]

AAPL_QUARTERLY_INCOME = [
    {"date": "2025-12-27", "symbol": "AAPL", "period": "Q1", "revenue": 124300000000, "netIncome": 36330000000, "eps": 2.42, "epsDiluted": 2.40},
    {"date": "2025-09-27", "symbol": "AAPL", "period": "Q4", "revenue": 94930000000, "netIncome": 24780000000, "eps": 1.65, "epsDiluted": 1.64},
    {"date": "2025-06-28", "symbol": "AAPL", "period": "Q3", "revenue": 85777000000, "netIncome": 21448000000, "eps": 1.41, "epsDiluted": 1.40},
    {"date": "2025-03-29", "symbol": "AAPL", "period": "Q2", "revenue": 95367000000, "netIncome": 23627000000, "eps": 1.55, "epsDiluted": 1.53},
]
