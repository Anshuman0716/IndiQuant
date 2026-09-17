"""Tests for growth factors."""
import numpy as np
import pandas as pd
from datetime import date
import pytest

from indiquant.factors.growth import (
    sales_cagr_3y,
    pat_cagr_5y,
    yoy_acceleration,
    qoq_inflection,
)

class MockContext:
    def __init__(self, data: pd.DataFrame):
        self.data = data
        
    def get_fundamentals_history(self, asof, columns, lookback_years, max_staleness_days=200, table=""):
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in self.data.columns]
        return self.data[cols].copy()

def test_sales_cagr_3y():
    # 17 quarters needed for 3yr CAGR (Q0 to Q12 diff requires 13, plus 3 preceding for TTM = 16)
    # TTM at Q12 = 100. TTM at Q0 = 133.1 (which is exactly a 10% CAGR over 3 years)
    # (133.1/100)^(1/3) - 1 = 0.10
    
    # We just need to mock the TTM sums implicitly by mocking the quarters
    # Q15 to Q12 sum to 100
    # Q3 to Q0 sum to 133.1
    df = pd.DataFrame({
        "isin": ["A"] * 16,
        "quarter_end": pd.date_range("2017-03-31", periods=16, freq="QE"),
        "knowledge_date": pd.date_range("2017-04-15", periods=16, freq="QE"),
        "revenue": [25, 25, 25, 25] + [30] * 8 + [33.275] * 4 # Q12 TTM=100. Q0 TTM=133.1
    })
    ctx = MockContext(df)
    res = sales_cagr_3y(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 10.0)

def test_pat_cagr_5y():
    # 24 quarters needed (20 diff + 3 preceding)
    # TTM at Q20 = 100. TTM at Q0 = 161.051 (10% CAGR over 5 years)
    df = pd.DataFrame({
        "isin": ["A"] * 24,
        "quarter_end": pd.date_range("2015-03-31", periods=24, freq="QE"),
        "knowledge_date": pd.date_range("2015-04-15", periods=24, freq="QE"),
        "pat": [25] * 4 + [30] * 16 + [40.26275] * 4
    })
    ctx = MockContext(df)
    res = pat_cagr_5y(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 10.0, rtol=1e-3)

def test_yoy_acceleration():
    # 12 quarters needed (Q0, Q4, Q8 TTMs)
    # Q8 TTM = 100
    # Q4 TTM = 110 (10% growth)
    # Q0 TTM = 132 (20% growth)
    # Acceleration = 20% - 10% = 10%
    df = pd.DataFrame({
        "isin": ["A"] * 12,
        "quarter_end": pd.date_range("2018-03-31", periods=12, freq="QE"),
        "knowledge_date": pd.date_range("2018-04-15", periods=12, freq="QE"),
        "revenue": [25] * 4 + [27.5] * 4 + [33.0] * 4
    })
    ctx = MockContext(df)
    res = yoy_acceleration(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 10.0)

def test_qoq_inflection():
    # 6 quarters needed (Q0, Q1, Q4, Q5)
    # Q5 rev = 100
    # Q4 rev = 110 (Q5->Q4 YoY is not relevant, we need Q1 YoY and Q0 YoY)
    # Let's say:
    # Q5(Prev Yr Q-1) = 100, Q1(Curr Yr Q-1) = 110 (10% YoY growth)
    # Q4(Prev Yr Q0) = 100, Q0(Curr Yr Q0) = 120 (20% YoY growth)
    # Inflection = 20% - 10% = +10%
    df = pd.DataFrame({
        "isin": ["A"] * 6,
        "quarter_end": pd.date_range("2019-09-30", periods=6, freq="QE"),
        "knowledge_date": pd.date_range("2019-10-15", periods=6, freq="QE"),
        "revenue": [100, 100, 99, 99, 110, 120] 
        # q_idx:      5,   4,  3,  2,   1,   0
        # Q5=100, Q4=100, Q1=110, Q0=120
    })
    ctx = MockContext(df)
    res = qoq_inflection(ctx, date(2021, 4, 1))
    assert np.isclose(res.loc["A"], 10.0)
