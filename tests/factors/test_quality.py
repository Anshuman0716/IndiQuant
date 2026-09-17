"""Tests for quality factors."""
import numpy as np
import pandas as pd
from datetime import date
import pytest

from indiquant.factors.quality import (
    roce_ttm,
    roe_ttm,
    gross_profitability,
    opm_stability_5y,
    cfo_pat_ratio,
    accruals_ratio,
    piotroski_f_score,
)

class MockContext:
    def __init__(self, data: pd.DataFrame):
        self.data = data
        
    def get_fundamentals_history(self, asof, columns, lookback_years, max_staleness_days=200, table=""):
        # Select columns available
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in self.data.columns]
        return self.data[cols].copy()
        
    def get_fundamentals(self, asof, columns, max_staleness_days=200, table=""):
        # Simplified: just return the last row per ISIN
        df = self.data.groupby("isin").last().reset_index()
        df["is_missing"] = False
        cols = ["isin", "quarter_end", "knowledge_date"] + [c for c in columns if c in df.columns] + ["is_missing"]
        return df[cols].copy()

def test_roe_ttm():
    # 4 quarters of data for ISIN A
    df = pd.DataFrame({
        "isin": ["A"] * 4,
        "quarter_end": pd.date_range("2020-03-31", periods=4, freq="QE"),
        "knowledge_date": pd.date_range("2020-04-15", periods=4, freq="QE"),
        "pat": [10, 20, 30, 40], # TTM PAT = 100
        "total_assets": [1000, 1000, 1000, 2000],
        "current_liabilities": [100, 100, 100, 200],
        "non_current_liabilities": [400, 400, 400, 800],
        # latest Equity = 2000 - (200 + 800) = 1000
        # ROE = 100 / 1000 = 10%
    })
    ctx = MockContext(df)
    res = roe_ttm(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 10.0)

def test_gross_profitability():
    df = pd.DataFrame({
        "isin": ["A", "B"],
        "quarter_end": [pd.Timestamp("2020-12-31")] * 2,
        "knowledge_date": [pd.Timestamp("2021-01-15")] * 2,
        "revenue": [1000, 1000],
        "raw_material_cost": [600, np.nan],
        "pat": [0, 100],
        "interest": [0, 50],
        "tax": [0, 50],
        "total_assets": [2000, 2000],
    })
    # A has RM cost: GP = 1000 - 600 = 400. GP/Assets = 400/2000 = 20%
    # B fallback to EBIT: 100 + 50 + 50 = 200. GP/Assets = 200/2000 = 10%
    ctx = MockContext(df)
    res = gross_profitability(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 20.0)
    assert np.isclose(res.loc["B"], 10.0)

def test_accruals_ratio():
    # 4 quarters
    df = pd.DataFrame({
        "isin": ["A"] * 4,
        "quarter_end": pd.date_range("2020-03-31", periods=4, freq="QE"),
        "knowledge_date": pd.date_range("2020-04-15", periods=4, freq="QE"),
        "operating_cash_flow": [10, 10, 10, 10], # CFO TTM = 40
        "pat": [20, 20, 20, 20], # PAT TTM = 80
        "total_assets": [1000, 1000, 1000, 1000], # Assets = 1000
        # Accruals = (80 - 40) / 1000 = 4%
    })
    ctx = MockContext(df)
    res = accruals_ratio(ctx, date(2021, 1, 1))
    assert np.isclose(res.loc["A"], 4.0)

def test_piotroski_f_score():
    # 8 quarters (Current + 4 trailing to compare YoY + 3 more so Yr1 has TTM)
    df = pd.DataFrame({
        "isin": ["A"] * 8,
        "quarter_end": pd.date_range("2019-06-30", periods=8, freq="QE"),
        "knowledge_date": pd.date_range("2019-07-15", periods=8, freq="QE"),
        # Q1-Q4 (Yr1 TTM): PAT=100, CFO=50
        # Q5-Q8 (Yr2 TTM): PAT=120, CFO=150
        "pat": [25, 25, 25, 25, 30, 30, 30, 30], # Yr1 sum=100, Yr2 sum=120
        "operating_cash_flow": [10, 15, 15, 10, 30, 40, 40, 40], # Yr1 sum=50, Yr2 sum=150
        "total_assets": [1000] * 8,
    })
    ctx = MockContext(df)
    res = piotroski_f_score(ctx, date(2021, 4, 1))
    
    # Yr2 checks:
    # 1. ROA > 0 ? (120/1000) -> 1
    # 2. CFO > 0 ? (150) -> 1
    # 3. ROA_current > ROA_prev ? (120/1000 > 100/1000) -> 1
    # 4. CFO > PAT ? (150 > 120) -> 1
    # Total = 4 points. Scaled by 9/4 = 9.0
    assert np.isclose(res.loc["A"], 9.0)
