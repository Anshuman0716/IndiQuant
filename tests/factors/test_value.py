"""Tests for value factors."""
import numpy as np
import pandas as pd
from datetime import date
import pytest

from indiquant.factors.value import (
    pe_ratio,
    pb_ratio,
    ev_ebitda,
    ev_sales,
    fcf_yield,
    earnings_yield,
)

class MockContext:
    def __init__(self, fundas: pd.DataFrame, prices: pd.DataFrame):
        self.fundas = fundas
        self.prices = prices
        
    def get_fundamentals_history(self, asof, columns, lookback_years, max_staleness_days=200, table=""):
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in self.fundas.columns]
        return self.fundas[cols].copy()
        
    def get_fundamentals(self, asof, columns, max_staleness_days=200, table=""):
        df = self.fundas.groupby("isin").last().reset_index()
        df["is_missing"] = False
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in df.columns] + ["is_missing"]
        return df[cols].copy()
        
    def get_prices(self, asof, lookback_days):
        return self.prices.copy()

@pytest.fixture
def mock_ctx():
    # 4 quarters of fundamentals
    f_df = pd.DataFrame({
        "isin": ["A"] * 4,
        "quarter_end": pd.date_range("2020-03-31", periods=4, freq="QE"),
        "knowledge_date": pd.date_range("2020-04-15", periods=4, freq="QE"),
        "pat": [10, 10, 10, 10], # TTM = 40
        "revenue": [100, 100, 100, 100], # TTM = 400
        "interest": [5, 5, 5, 5],
        "tax": [5, 5, 5, 5],
        "depreciation": [10, 10, 10, 10],
        # EBIT = 10+5+5 = 20 -> TTM = 80
        # EBITDA = 20+10 = 30 -> TTM = 120
        "operating_cash_flow": [20, 20, 20, 20],
        "capex": [5, 5, 5, 5], # FCF = 15 -> TTM = 60
        "total_assets": [1000] * 4,
        "current_liabilities": [200] * 4,
        "non_current_liabilities": [300] * 4, # Equity = 1000 - 500 = 500
        "total_debt": [400] * 4,
        "cash_and_equivalents": [100] * 4,
        "shares_outstanding": [100] * 4,
    })
    
    # Prices
    p_df = pd.DataFrame({
        "isin": ["A"],
        "date": [pd.Timestamp("2021-01-01")],
        "close": [10.0], # Market Cap = 10 * 100 = 1000
        "volume": [1000],
    })
    
    return MockContext(f_df, p_df)


def test_pe_ratio(mock_ctx):
    # Market Cap = 1000. PAT TTM = 40. P/E = 1000/40 = 25
    res = pe_ratio(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 25.0)

def test_pb_ratio(mock_ctx):
    # Market Cap = 1000. Equity = 500. P/B = 1000/500 = 2.0
    res = pb_ratio(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 2.0)

def test_ev_ebitda(mock_ctx):
    # Market Cap = 1000. Debt = 400. Cash = 100. EV = 1300.
    # EBITDA TTM = 120. EV/EBITDA = 1300 / 120 = 10.8333
    res = ev_ebitda(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 1300 / 120.0)

def test_ev_sales(mock_ctx):
    # EV = 1300. Revenue TTM = 400. EV/Sales = 1300 / 400 = 3.25
    res = ev_sales(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 1300 / 400.0)

def test_fcf_yield(mock_ctx):
    # FCF TTM = 60. Market Cap = 1000. Yield = 6%
    res = fcf_yield(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 6.0)

def test_earnings_yield(mock_ctx):
    # EBIT TTM = 80. EV = 1300. Yield = 80 / 1300 * 100 = 6.1538%
    res = earnings_yield(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 80 / 1300.0 * 100.0)
