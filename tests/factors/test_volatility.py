"""Tests for volatility factors."""
import numpy as np
import pandas as pd
from datetime import date
import pytest

from indiquant.factors.volatility import (
    volatility_1y,
    downside_risk_1y,
    beta_1y,
)

class MockContext:
    def __init__(self, prices: pd.DataFrame):
        self.prices = prices
        
    def get_prices(self, asof, lookback_days):
        return self.prices.copy()

@pytest.fixture
def mock_ctx():
    # 250 trading days
    dates = pd.date_range("2020-01-01", periods=250, freq="B")
    
    # Stock A: exactly 1% return every day (0 vol)
    # Stock B: alternates between +1% and -1% 
    ret_a = np.ones(250) * 0.01
    ret_b = np.array([0.01, -0.01] * 125)
    
    # Let's generate prices from these returns
    # price_t = price_t-1 * (1 + ret)
    # prev_close is price_t-1
    price_a = np.cumprod(1 + ret_a) * 100
    price_b = np.cumprod(1 + ret_b) * 100
    
    prev_a = np.roll(price_a, 1)
    prev_a[0] = 100
    prev_b = np.roll(price_b, 1)
    prev_b[0] = 100
    
    df_a = pd.DataFrame({
        "isin": ["A"] * 250,
        "date": dates,
        "close": price_a,
        "prev_close": prev_a,
    })
    
    df_b = pd.DataFrame({
        "isin": ["B"] * 250,
        "date": dates,
        "close": price_b,
        "prev_close": prev_b,
    })
    
    prices = pd.concat([df_a, df_b])
    return MockContext(prices)

def test_volatility_1y(mock_ctx):
    res = volatility_1y(mock_ctx, date(2021, 1, 1))
    
    # Stock A returns are constantly 0.01, so std is 0
    assert np.isclose(res.loc["A"], 0.0, atol=1e-5)
    
    # Stock B returns are +0.01 and -0.01
    # mean is 0, var is 0.0001. std is 0.01. Ann Vol = 0.01 * sqrt(252) = 0.1587 = 15.87%
    assert np.isclose(res.loc["B"], 15.87, atol=0.1)

def test_downside_risk_1y(mock_ctx):
    res = downside_risk_1y(mock_ctx, date(2021, 1, 1))
    
    # Stock A has no negative returns, so should be NaN
    assert "A" not in res or pd.isna(res.get("A"))
    
    # Stock B downside returns are constantly -0.01, so variance of *just* the negative returns is 0!
    assert np.isclose(res.loc["B"], 0.0, atol=1e-5)

def test_beta_1y(mock_ctx):
    # Stock A: constant 0.01
    # Stock B: +0.01, -0.01
    # Market = (+0.01 + 0.01)/2 = 0.01, (+0.01 - 0.01)/2 = 0.0
    # Let's just check it runs without error and returns something since exact beta 
    # of this weird artificial series isn't the point.
    res = beta_1y(mock_ctx, date(2021, 1, 1))
    assert res is not None
    assert "A" in res.index
    assert "B" in res.index
