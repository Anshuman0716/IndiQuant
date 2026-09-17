"""Growth factors."""

from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor

logger = structlog.get_logger(__name__)


def _compute_cagr(df: pd.DataFrame, col: str, periods: int) -> pd.Series:
    """Helper to compute CAGR over a given number of periods (years).
    Requires df to be a TTM timeseries with 'rn' descending counter.
    """
    if df.empty or f"{col}_ttm" not in df.columns:
        return pd.Series(dtype=float, index=df["isin"].unique() if not df.empty else [])
        
    current = df[df["rn"] == 0].set_index("isin")[f"{col}_ttm"]
    # 3 years = 12 quarters ago. 5 years = 20 quarters ago.
    q_ago = periods * 4
    past = df[df["rn"] == q_ago].set_index("isin")[f"{col}_ttm"]
    
    # We can only compute CAGR if both ends are positive
    valid = (current > 0) & (past > 0)
    
    cagr = (current / past) ** (1.0 / periods) - 1.0
    return (cagr * 100.0).where(valid, np.nan)


@factor(
    id="sales_cagr_3y",
    pillar="GROWTH",
    direction=1,
    min_history_days=365 * 4, # 3 years + 1 year for TTM
    required_tables=["fundamentals"],
    unit="%",
)
def sales_cagr_3y(ctx: FactorContext, asof: date) -> pd.Series:
    """3-Year Revenue CAGR."""
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue"],
        lookback_years=5,
    )
    if fundas.empty or "revenue" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["revenue_ttm"] = fundas.groupby("isin")["revenue"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    fundas["rn"] = fundas.groupby("isin").cumcount(ascending=False)
    
    return _compute_cagr(fundas, "revenue", 3)


@factor(
    id="pat_cagr_5y",
    pillar="GROWTH",
    direction=1,
    min_history_days=365 * 6, # 5 years + 1 year for TTM
    required_tables=["fundamentals"],
    unit="%",
)
def pat_cagr_5y(ctx: FactorContext, asof: date) -> pd.Series:
    """5-Year Profit After Tax CAGR."""
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat"],
        lookback_years=7,
    )
    if fundas.empty or "pat" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["pat_ttm"] = fundas.groupby("isin")["pat"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    fundas["rn"] = fundas.groupby("isin").cumcount(ascending=False)
    
    return _compute_cagr(fundas, "pat", 5)


@factor(
    id="yoy_acceleration",
    pillar="GROWTH",
    direction=1,
    min_history_days=365 * 2,
    required_tables=["fundamentals"],
    unit="%",
)
def yoy_acceleration(ctx: FactorContext, asof: date) -> pd.Series:
    """Revenue Growth Acceleration.
    
    Formula: (Current TTM / Prev TTM) - (Prev TTM / TTM 2 Yrs Ago)
    Positive values mean growth is speeding up.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue"],
        lookback_years=3,
    )
    if fundas.empty or "revenue" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["rev_ttm"] = fundas.groupby("isin")["revenue"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    fundas["rn"] = fundas.groupby("isin").cumcount(ascending=False)
    
    t0 = fundas[fundas["rn"] == 0].set_index("isin")["rev_ttm"]
    t1 = fundas[fundas["rn"] == 4].set_index("isin")["rev_ttm"]
    t2 = fundas[fundas["rn"] == 8].set_index("isin")["rev_ttm"]
    
    valid = (t0 > 0) & (t1 > 0) & (t2 > 0)
    
    g1 = (t0 / t1) - 1.0
    g2 = (t1 / t2) - 1.0
    
    accel = (g1 - g2) * 100.0
    return accel.where(valid, np.nan)


@factor(
    id="qoq_inflection",
    pillar="GROWTH",
    direction=1,
    min_history_days=365,
    required_tables=["fundamentals"],
    unit="%",
)
def qoq_inflection(ctx: FactorContext, asof: date) -> pd.Series:
    """Quarter-on-Quarter Inflection.
    
    Formula: Current Qtr YoY Growth - Previous Qtr YoY Growth
    Helps spot immediate turnaround in momentum before TTM catches up.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue"],
        lookback_years=2,
    )
    if fundas.empty or "revenue" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["rn"] = fundas.groupby("isin").cumcount(ascending=False)
    
    # Q0 vs Q4 (Current YoY)
    q0 = fundas[fundas["rn"] == 0].set_index("isin")["revenue"]
    q4 = fundas[fundas["rn"] == 4].set_index("isin")["revenue"]
    
    # Q1 vs Q5 (Previous YoY)
    q1 = fundas[fundas["rn"] == 1].set_index("isin")["revenue"]
    q5 = fundas[fundas["rn"] == 5].set_index("isin")["revenue"]
    
    valid = (q0 > 0) & (q4 > 0) & (q1 > 0) & (q5 > 0)
    
    g_curr = (q0 / q4) - 1.0
    g_prev = (q1 / q5) - 1.0
    
    inflection = (g_curr - g_prev) * 100.0
    return inflection.where(valid, np.nan)
