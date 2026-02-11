"""Shared test fixtures."""

from __future__ import annotations

import pytest
import respx
import httpx

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


# --- Sample response data ---

AAPL_PROFILE = [{
    "symbol": "AAPL",
    "companyName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "ceo": "Mr. Timothy D. Cook",
    "fullTimeEmployees": "164000",
    "description": "Apple Inc. designs, manufactures, and markets smartphones...",
    "exchangeShortName": "NASDAQ",
    "country": "US",
    "website": "https://www.apple.com",
}]

AAPL_QUOTE = [{
    "symbol": "AAPL",
    "price": 189.84,
    "marketCap": 2950000000000,
    "volume": 55000000,
    "avgVolume": 60000000,
    "changesPercentage": 1.25,
    "dayLow": 188.50,
    "dayHigh": 190.50,
    "yearLow": 164.08,
    "yearHigh": 199.62,
    "eps": 6.42,
    "pe": 29.57,
}]

AAPL_RATIOS = [{
    "peRatioTTM": 29.57,
    "priceToBookRatioTTM": 47.15,
    "priceToSalesRatioTTM": 7.84,
    "pegRatioTTM": 2.1,
    "enterpriseValueOverEBITDATTM": 24.5,
    "dividendYieldTTM": 0.005,
    "returnOnEquityTTM": 1.56,
    "returnOnAssetsTTM": 0.33,
    "debtEquityRatioTTM": 1.87,
    "currentRatioTTM": 0.99,
    "grossProfitMarginTTM": 0.46,
    "operatingProfitMarginTTM": 0.30,
    "netProfitMarginTTM": 0.26,
    "freeCashFlowYieldTTM": 0.034,
}]

AAPL_INCOME = [
    {
        "date": "2024-09-28",
        "period": "FY",
        "revenue": 391035000000,
        "grossProfit": 180683000000,
        "operatingIncome": 123216000000,
        "netIncome": 93736000000,
        "eps": 6.08,
        "epsdiluted": 6.08,
    },
    {
        "date": "2023-09-30",
        "period": "FY",
        "revenue": 383285000000,
        "grossProfit": 169148000000,
        "operatingIncome": 114301000000,
        "netIncome": 96995000000,
        "eps": 6.16,
        "epsdiluted": 6.13,
    },
    {
        "date": "2022-09-24",
        "period": "FY",
        "revenue": 394328000000,
        "grossProfit": 170782000000,
        "operatingIncome": 119437000000,
        "netIncome": 99803000000,
        "eps": 6.15,
        "epsdiluted": 6.11,
    },
    {
        "date": "2021-09-25",
        "period": "FY",
        "revenue": 365817000000,
        "grossProfit": 152836000000,
        "operatingIncome": 108949000000,
        "netIncome": 94680000000,
        "eps": 5.67,
        "epsdiluted": 5.61,
    },
]

AAPL_BALANCE = [
    {"date": "2024-09-28", "totalAssets": 364980000000, "totalLiabilities": 308030000000, "totalStockholdersEquity": 56950000000, "totalDebt": 97300000000, "cashAndCashEquivalents": 29943000000, "netDebt": 49070000000},
    {"date": "2023-09-30", "totalAssets": 352583000000, "totalLiabilities": 290437000000, "totalStockholdersEquity": 62146000000, "totalDebt": 111088000000, "cashAndCashEquivalents": 29965000000, "netDebt": 81123000000},
    {"date": "2022-09-24", "totalAssets": 352755000000, "totalLiabilities": 302083000000, "totalStockholdersEquity": 50672000000, "totalDebt": 120069000000, "cashAndCashEquivalents": 23646000000, "netDebt": 96423000000},
    {"date": "2021-09-25", "totalAssets": 351002000000, "totalLiabilities": 287912000000, "totalStockholdersEquity": 63090000000, "totalDebt": 124719000000, "cashAndCashEquivalents": 34940000000, "netDebt": 89779000000},
]

AAPL_CASHFLOW = [
    {"date": "2024-09-28", "operatingCashFlow": 118254000000, "capitalExpenditure": -9959000000, "freeCashFlow": 108295000000, "dividendsPaid": -15025000000, "commonStockRepurchased": -94949000000},
    {"date": "2023-09-30", "operatingCashFlow": 110543000000, "capitalExpenditure": -11052000000, "freeCashFlow": 99584000000, "dividendsPaid": -15025000000, "commonStockRepurchased": -77550000000},
    {"date": "2022-09-24", "operatingCashFlow": 122151000000, "capitalExpenditure": -10708000000, "freeCashFlow": 111443000000, "dividendsPaid": -14841000000, "commonStockRepurchased": -89402000000},
    {"date": "2021-09-25", "operatingCashFlow": 104038000000, "capitalExpenditure": -11085000000, "freeCashFlow": 92953000000, "dividendsPaid": -14467000000, "commonStockRepurchased": -85971000000},
]

AAPL_PRICE_TARGET = [{
    "symbol": "AAPL",
    "targetConsensus": 210.50,
    "targetHigh": 250.00,
    "targetLow": 170.00,
    "targetMedian": 215.00,
}]

AAPL_GRADES = [{
    "symbol": "AAPL",
    "buy": 25,
    "overweight": 5,
    "hold": 8,
    "underweight": 1,
    "sell": 1,
    "consensus": "Buy",
}]

AAPL_RATING = [{
    "symbol": "AAPL",
    "rating": "S",
    "ratingScore": 5,
    "ratingDetailsDCFScore": 5,
    "ratingDetailsROEScore": 5,
    "ratingDetailsROAScore": 3,
    "ratingDetailsDEScore": 3,
    "ratingDetailsPEScore": 3,
    "ratingDetailsPBScore": 3,
}]

AAPL_SEARCH = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchangeShortName": "NASDAQ"},
    {"symbol": "AAPD", "name": "Direxion Daily AAPL Bear 1X", "exchangeShortName": "NASDAQ"},
]

AAPL_HISTORICAL = {
    "symbol": "AAPL",
    "historical": [
        {"date": "2025-01-31", "close": 189.84, "volume": 55000000},
        {"date": "2025-01-30", "close": 188.50, "volume": 52000000},
        {"date": "2025-01-29", "close": 187.20, "volume": 48000000},
    ] + [
        {"date": f"2025-01-{28 - i:02d}", "close": 185.0 + i * 0.5, "volume": 50000000}
        for i in range(28)
    ],
}

AAPL_EARNINGS_UPCOMING = [
    {
        "symbol": "AAPL",
        "date": "2025-04-24",
        "epsEstimated": 1.62,
        "revenueEstimated": 94500000000,
        "fiscalDateEnding": "2025-03-31",
        "time": "amc",
    }
]

AAPL_EARNINGS_HISTORICAL = [
    {"date": "2025-01-30", "symbol": "AAPL", "eps": 2.40, "epsEstimated": 2.35, "revenue": 124300000000, "revenueEstimated": 121100000000, "fiscalDateEnding": "2024-12-31"},
    {"date": "2024-10-31", "symbol": "AAPL", "eps": 1.64, "epsEstimated": 1.60, "revenue": 94930000000, "revenueEstimated": 94580000000, "fiscalDateEnding": "2024-09-30"},
    {"date": "2024-08-01", "symbol": "AAPL", "eps": 1.40, "epsEstimated": 1.35, "revenue": 85777000000, "revenueEstimated": 84530000000, "fiscalDateEnding": "2024-06-30"},
    {"date": "2024-05-02", "symbol": "AAPL", "eps": 1.53, "epsEstimated": 1.50, "revenue": 90753000000, "revenueEstimated": 90010000000, "fiscalDateEnding": "2024-03-31"},
]
