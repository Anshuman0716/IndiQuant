"""Microstructure factors.

These factors capture liquidity, trading friction, and intraday behaviors.
"""
from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor

logger = structlog.get_logger(__name__)


@factor(
    id="amihud_illiquidity",
    pillar="MICROSTRUCTURE",
    direction=-1,  # Lower illiquidity is better (more liquid)
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="idx",
)
def amihud_illiquidity(ctx: FactorContext, asof: date) -> pd.Series:
    """Amihud Illiquidity Measure (1 Year).
    
    Formula: Average of ( |Daily Return| / Rupee Volume ) over 252 days.
    Measures price impact of a single rupee of trading volume.
    Requires at least 200 trading days.
    """
    prices = ctx.get_prices(asof, lookback_days=365)
    if prices.empty:
        return pd.Series(dtype=float)
        
    prices = prices.sort_values(["isin", "date"])
    
    # Calculate daily returns
    prices["ret"] = (prices["close"] - prices["prev_close"]) / prices["prev_close"]
    
    # Rupee volume (we have `turnover` in our silver table for NSE, which is in rupees)
    if "turnover" not in prices.columns:
        # Fallback if turnover missing: volume * close
        prices["rupee_volume"] = prices["volume"] * prices["close"]
    else:
        prices["rupee_volume"] = prices["turnover"]
        
    prices["amihud_daily"] = prices["ret"].abs() / prices["rupee_volume"]
    prices["amihud_daily"] = prices["amihud_daily"].replace([np.inf, -np.inf], np.nan)
    
    # We want average over exactly the last 252 available rows per ISIN
    prices["rn"] = prices.groupby("isin").cumcount(ascending=False)
    prices_1yr = prices[prices["rn"] < 252]
    
    def _calc_amihud(g):
        if len(g.dropna(subset=["amihud_daily"])) < 200:
            return np.nan
        # Multiply by 10^7 or similar scale factor as raw amihud is tiny
        return g["amihud_daily"].mean() * 1e7
        
    res = prices_1yr.groupby("isin").apply(_calc_amihud, include_groups=False)
    return res


@factor(
    id="turnover_ratio_1y",
    pillar="MICROSTRUCTURE",
    direction=1,  # Higher is more liquid
    min_history_days=252,
    required_tables=["equity_daily", "fundamentals"],
    unit="%",
)
def turnover_ratio_1y(ctx: FactorContext, asof: date) -> pd.Series:
    """Annual Share Turnover Ratio.
    
    Formula: Sum of Volume over 1 year / Shares Outstanding
    """
    prices = ctx.get_prices(asof, lookback_days=365)
    fundas = ctx.get_fundamentals(
        asof,
        columns=["shares_outstanding"]
    )
    
    if prices.empty or fundas.empty or "shares_outstanding" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas = fundas[~fundas["is_missing"]].set_index("isin")
        
    prices = prices.sort_values(["isin", "date"])
    prices["rn"] = prices.groupby("isin").cumcount(ascending=False)
    prices_1yr = prices[prices["rn"] < 252]
    
    # Sum of volume
    vol_sum = prices_1yr.groupby("isin")["volume"].sum()
    
    # Drop ISINs with fewer than 200 trading days
    counts = prices_1yr.groupby("isin").size()
    vol_sum = vol_sum.where(counts >= 200, np.nan)
    
    ratio = vol_sum / fundas["shares_outstanding"]
    return (ratio * 100.0).replace([np.inf, -np.inf], np.nan)


@factor(
    id="close_to_high_ratio",
    pillar="MICROSTRUCTURE",
    direction=1,  # Higher means it consistently closes near the high of the day
    min_history_days=30,
    required_tables=["equity_daily"],
    unit="%",
)
def close_to_high_ratio(ctx: FactorContext, asof: date) -> pd.Series:
    """Intraday Close-to-High Ratio (1 month).
    
    Formula: Average of (Close - Low) / (High - Low) over the last 21 days.
    Captures intraday momentum/buying pressure into the close.
    """
    prices = ctx.get_prices(asof, lookback_days=40)
    if prices.empty:
        return pd.Series(dtype=float)
        
    prices = prices.sort_values(["isin", "date"])
    
    # Range
    prices["range"] = prices["high"] - prices["low"]
    
    # (Close - Low) / Range
    prices["c2h"] = (prices["close"] - prices["low"]) / prices["range"]
    prices["c2h"] = prices["c2h"].replace([np.inf, -np.inf], np.nan)
    
    # We want average over exactly the last 21 available rows per ISIN
    prices["rn"] = prices.groupby("isin").cumcount(ascending=False)
    prices_1m = prices[prices["rn"] < 21]
    
    def _calc_c2h(g):
        if len(g.dropna(subset=["c2h"])) < 15: # Need at least 15 valid days
            return np.nan
        return g["c2h"].mean() * 100.0
        
    res = prices_1m.groupby("isin").apply(_calc_c2h, include_groups=False)
    return res
