"""Value factors."""

from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor
from indiquant.factors.transform import z_score

logger = structlog.get_logger(__name__)


@factor(
    id="pe_ratio",
    pillar="VALUATION",
    direction=-1,  # Lower P/E is better
    min_history_days=365,
    required_tables=["fundamentals", "equity_daily"],
    unit="x",
)
def pe_ratio(ctx: FactorContext, asof: date) -> pd.Series:
    """Price to Earnings Ratio (TTM).
    
    Formula: Market Cap / PAT_TTM
    Requires shares_outstanding to compute Market Cap.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat", "shares_outstanding"],
        lookback_years=2,
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    # Get latest price
    latest_prices = prices.groupby("isin").last()["close"]
    
    # Get latest shares and calculate TTM PAT
    fundas["pat_ttm"] = fundas.groupby("isin")["pat"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    latest_fundas = fundas.groupby("isin").last()
    
    mcap = latest_prices * latest_fundas["shares_outstanding"]
    pe = mcap / latest_fundas["pat_ttm"]
    
    # Filter negative P/E
    pe = pe.where(latest_fundas["pat_ttm"] > 0, np.nan)
    return pe.replace([np.inf, -np.inf], np.nan)


@factor(
    id="pb_ratio",
    pillar="VALUATION",
    direction=-1,  # Lower P/B is better
    min_history_days=90,
    required_tables=["fundamentals", "equity_daily"],
    unit="x",
)
def pb_ratio(ctx: FactorContext, asof: date) -> pd.Series:
    """Price to Book Ratio.
    
    Formula: Market Cap / Total_Equity
    where Total_Equity = Total Assets - Total Liabilities
    """
    fundas = ctx.get_fundamentals(
        asof,
        columns=["total_assets", "current_liabilities", "non_current_liabilities", "shares_outstanding"],
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas = fundas[~fundas["is_missing"]].set_index("isin")
    latest_prices = prices.groupby("isin").last()["close"]
    
    fundas["total_liabilities"] = fundas["current_liabilities"].fillna(0) + fundas.get("non_current_liabilities", 0)
    fundas["equity"] = fundas["total_assets"].fillna(0) - fundas["total_liabilities"]
    
    mcap = latest_prices * fundas["shares_outstanding"]
    pb = mcap / fundas["equity"]
    
    # Filter negative P/B
    pb = pb.where(fundas["equity"] > 0, np.nan)
    return pb.replace([np.inf, -np.inf], np.nan)


@factor(
    id="ev_ebitda",
    pillar="VALUATION",
    direction=-1,  # Lower EV/EBITDA is better
    min_history_days=365,
    required_tables=["fundamentals", "equity_daily"],
    unit="x",
)
def ev_ebitda(ctx: FactorContext, asof: date) -> pd.Series:
    """Enterprise Value to EBITDA (TTM).
    
    Formula: (Market Cap + Debt - Cash) / EBITDA_TTM
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat", "interest", "tax", "depreciation", "total_debt", "cash_and_equivalents", "shares_outstanding"],
        lookback_years=2,
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    # EBITDA = PAT + Interest + Tax + Depreciation
    fundas["ebitda"] = (
        fundas["pat"].fillna(0) + 
        fundas["interest"].fillna(0) + 
        fundas["tax"].fillna(0) + 
        fundas.get("depreciation", 0)
    )
    
    fundas["ebitda_ttm"] = fundas.groupby("isin")["ebitda"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    latest_fundas = fundas.groupby("isin").last()
    latest_prices = prices.groupby("isin").last()["close"]
    
    mcap = latest_prices * latest_fundas["shares_outstanding"]
    ev = mcap + latest_fundas.get("total_debt", 0) - latest_fundas.get("cash_and_equivalents", 0)
    
    ev_to_ebitda = ev / latest_fundas["ebitda_ttm"]
    
    # Filter negative EV/EBITDA
    ev_to_ebitda = ev_to_ebitda.where(latest_fundas["ebitda_ttm"] > 0, np.nan)
    return ev_to_ebitda.replace([np.inf, -np.inf], np.nan)


@factor(
    id="ev_sales",
    pillar="VALUATION",
    direction=-1,  # Lower EV/Sales is better
    min_history_days=365,
    required_tables=["fundamentals", "equity_daily"],
    unit="x",
)
def ev_sales(ctx: FactorContext, asof: date) -> pd.Series:
    """Enterprise Value to Sales (TTM).
    
    Formula: (Market Cap + Debt - Cash) / Revenue_TTM
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue", "total_debt", "cash_and_equivalents", "shares_outstanding"],
        lookback_years=2,
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["revenue_ttm"] = fundas.groupby("isin")["revenue"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    latest_fundas = fundas.groupby("isin").last()
    latest_prices = prices.groupby("isin").last()["close"]
    
    mcap = latest_prices * latest_fundas["shares_outstanding"]
    ev = mcap + latest_fundas.get("total_debt", 0) - latest_fundas.get("cash_and_equivalents", 0)
    
    ev_to_sales = ev / latest_fundas["revenue_ttm"]
    return ev_to_sales.replace([np.inf, -np.inf], np.nan).where(latest_fundas["revenue_ttm"] > 0, np.nan)


@factor(
    id="fcf_yield",
    pillar="VALUATION",
    direction=1,  # Higher FCF yield is better
    min_history_days=365,
    required_tables=["fundamentals", "equity_daily"],
    unit="%",
)
def fcf_yield(ctx: FactorContext, asof: date) -> pd.Series:
    """Free Cash Flow Yield (TTM).
    
    Formula: FCF_TTM / Market Cap
    where FCF = Operating Cash Flow - Capex
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["operating_cash_flow", "capex", "shares_outstanding"],
        lookback_years=2,
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["fcf"] = fundas.get("operating_cash_flow", 0) - fundas.get("capex", 0)
    fundas["fcf_ttm"] = fundas.groupby("isin")["fcf"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    
    latest_fundas = fundas.groupby("isin").last()
    latest_prices = prices.groupby("isin").last()["close"]
    
    mcap = latest_prices * latest_fundas["shares_outstanding"]
    yield_ = (latest_fundas["fcf_ttm"] / mcap) * 100.0
    
    return yield_.replace([np.inf, -np.inf], np.nan).where(mcap > 0, np.nan)


@factor(
    id="earnings_yield",
    pillar="VALUATION",
    direction=1,  # Higher yield is better
    min_history_days=365,
    required_tables=["fundamentals", "equity_daily"],
    unit="%",
)
def earnings_yield(ctx: FactorContext, asof: date) -> pd.Series:
    """Earnings Yield (TTM).
    
    Formula: EBIT_TTM / Enterprise Value
    Greenblatt's favored metric.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat", "interest", "tax", "total_debt", "cash_and_equivalents", "shares_outstanding"],
        lookback_years=2,
    )
    prices = ctx.get_prices(asof, lookback_days=7)
    
    if fundas.empty or prices.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["ebit"] = fundas["pat"].fillna(0) + fundas["interest"].fillna(0) + fundas["tax"].fillna(0)
    fundas["ebit_ttm"] = fundas.groupby("isin")["ebit"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    
    latest_fundas = fundas.groupby("isin").last()
    latest_prices = prices.groupby("isin").last()["close"]
    
    mcap = latest_prices * latest_fundas["shares_outstanding"]
    ev = mcap + latest_fundas.get("total_debt", 0) - latest_fundas.get("cash_and_equivalents", 0)
    
    ey = (latest_fundas["ebit_ttm"] / ev) * 100.0
    return ey.replace([np.inf, -np.inf], np.nan).where(ev > 0, np.nan)
