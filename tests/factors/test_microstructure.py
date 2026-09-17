"""Tests for microstructure factors."""
import numpy as np
import pandas as pd
from datetime import date
import pytest

from indiquant.factors.microstructure import (
    amihud_illiquidity,
    turnover_ratio_1y,
    close_to_high_ratio,
)

class MockContext:
    def __init__(self, prices: pd.DataFrame, fundas: pd.DataFrame = None):
        self.prices = prices
        self.fundas = fundas
        
    def get_prices(self, asof, lookback_days):
        if "turnover" not in self.prices.columns:
            return self.prices.copy()
        # Mock get_prices to include turnover since it's present in actual silver table
        return self.prices.copy()
        
    def get_fundamentals(self, asof, columns, max_staleness_days=200, table=""):
        if self.fundas is None:
            return pd.DataFrame()
        df = self.fundas.groupby("isin").last().reset_index()
        df["is_missing"] = False
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in df.columns] + ["is_missing"]
        return df[cols].copy()

@pytest.fixture
def mock_ctx():
    # 250 trading days
    dates = pd.date_range("2020-01-01", periods=250, freq="B")
    
    df = pd.DataFrame({
        "isin": ["A"] * 250,
        "date": dates,
        "close": [105.0] * 250,
        "prev_close": [100.0] * 250, # 5% return every day
        "high": [110.0] * 250,
        "low": [100.0] * 250,
        "volume": [1000] * 250,
        "turnover": [105000] * 250,
    })
    
    fundas = pd.DataFrame({
        "isin": ["A"],
        "quarter_end": ["2020-12-31"],
        "knowledge_date": ["2021-01-15"],
        "shares_outstanding": [1000000],
    })
    
    return MockContext(df, fundas)

def test_amihud_illiquidity(mock_ctx):
    # ret = 0.05
    # turnover = 105000
    # amihud = 0.05 / 105000 = 4.7619e-7
    # scale by 1e7 = 4.7619
    res = amihud_illiquidity(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 4.7619, atol=1e-4)

def test_turnover_ratio(mock_ctx):
    # 250 days * 1000 vol = 250000
    # Shares = 1000000
    # Ratio = 250000 / 1000000 = 0.25 = 25%
    res = turnover_ratio_1y(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 25.0)

def test_close_to_high_ratio(mock_ctx):
    # Close = 105, Low = 100, High = 110
    # (Close - Low) / (High - Low) = 5 / 10 = 0.5 = 50%
    res = close_to_high_ratio(mock_ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 50.0)
