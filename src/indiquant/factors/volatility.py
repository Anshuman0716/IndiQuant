"""Volatility factors."""

from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor

logger = structlog.get_logger(__name__)


def _get_returns(ctx: FactorContext, asof: date, lookback_days: int) -> pd.DataFrame:
    """Helper to fetch prices and compute daily returns."""
    prices = ctx.get_prices(asof, lookback_days=lookback_days)
    if prices.empty:
        return pd.DataFrame()
        
    prices = prices.sort_values(["isin", "date"])
    # Calculate daily returns: (close - prev_close) / prev_close
    # We use prev_close instead of shift(1) to cleanly handle weekend/holiday gaps
    prices["ret"] = (prices["close"] - prices["prev_close"]) / prices["prev_close"]
    prices["ret"] = prices["ret"].replace([np.inf, -np.inf], np.nan)
    return prices.dropna(subset=["ret"])


@factor(
    id="volatility_1y",
    pillar="VOLATILITY",
    direction=-1,  # Lower volatility is better (typically)
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="std",
)
def volatility_1y(ctx: FactorContext, asof: date) -> pd.Series:
    """1-Year Annualized Volatility.
    
    Formula: Standard deviation of daily returns * sqrt(252).
    Requires at least 200 trading days.
    """
    returns = _get_returns(ctx, asof, lookback_days=365)
    if returns.empty:
        return pd.Series(dtype=float)
        
    def _ann_vol(x):
        if len(x) < 200:
            return np.nan
        return x.std() * np.sqrt(252)
        
    vol = returns.groupby("isin")["ret"].agg(_ann_vol)
    return vol * 100.0


@factor(
    id="downside_risk_1y",
    pillar="VOLATILITY",
    direction=-1,  # Lower downside risk is better
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="std",
)
def downside_risk_1y(ctx: FactorContext, asof: date) -> pd.Series:
    """1-Year Annualized Downside Volatility (Sortino denominator).
    
    Formula: Standard deviation of negative daily returns * sqrt(252).
    """
    returns = _get_returns(ctx, asof, lookback_days=365)
    if returns.empty:
        return pd.Series(dtype=float)
        
    # Only keep negative returns
    downside = returns[returns["ret"] < 0].copy()
    
    def _down_vol(x):
        if len(x) < 50: # Need sufficient negative days for a stable stat
            return np.nan
        return x.std() * np.sqrt(252)
        
    d_vol = downside.groupby("isin")["ret"].agg(_down_vol)
    return d_vol * 100.0


@factor(
    id="beta_1y",
    pillar="VOLATILITY",
    direction=0,  # Neutral metric (used for risk models rather than scoring)
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="x",
)
def beta_1y(ctx: FactorContext, asof: date) -> pd.Series:
    """1-Year Market Beta.
    
    Formula: Covariance(Stock, Market) / Variance(Market)
    The Market return is proxied as the equal-weighted average return of 
    all stocks in the universe for each day.
    """
    returns = _get_returns(ctx, asof, lookback_days=365)
    if returns.empty:
        return pd.Series(dtype=float)
        
    # Calculate proxy market return per day
    market_ret = returns.groupby("date")["ret"].mean().rename("mkt_ret")
    
    # Merge back to calculate covariance
    df = returns.merge(market_ret, on="date")
    
    def _calc_beta(g):
        if len(g) < 200:
            return np.nan
        cov_matrix = np.cov(g["ret"], g["mkt_ret"])
        if cov_matrix.shape != (2, 2) or cov_matrix[1, 1] == 0:
            return np.nan
        return cov_matrix[0, 1] / cov_matrix[1, 1]
        
    beta = df.groupby("isin").apply(_calc_beta, include_groups=False)
    return beta
