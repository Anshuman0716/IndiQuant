"""Factor diagnostics and evaluation.

Provides tools for calculating decile reports, information coefficients (IC),
and monotonicity of factor returns.
"""
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, registry

logger = structlog.get_logger(__name__)


def _get_forward_returns(
    ctx: FactorContext, 
    isins: list[str], 
    asof: date, 
    forward_days: int = 21
) -> pd.Series:
    """Calculate forward returns from asof to asof + forward_days."""
    target_date = asof + timedelta(days=forward_days)
    
    # We fetch prices from slightly before asof to slightly after target
    # to ensure we capture the closest trading days
    prices = ctx.get_prices(target_date, lookback_days=forward_days + 15)
    if prices.empty:
        return pd.Series(dtype=float, index=isins)
        
    prices = prices[prices["isin"].isin(isins)].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.as_unit("us")
    
    asof_dt = pd.Timestamp(asof).as_unit("us")
    target_dt = pd.Timestamp(target_date).as_unit("us")
    
    # Get price strictly ON or immediately BEFORE the asof date
    t0 = pd.DataFrame({"isin": isins, "target": asof_dt})
    t0["target"] = t0["target"].dt.as_unit("us")
    
    # Get price on or immediately BEFORE the target date
    t1 = pd.DataFrame({"isin": isins, "target": target_dt})
    t1["target"] = t1["target"].dt.as_unit("us")
    
    prices = prices.sort_values("date")
    
    p0 = pd.merge_asof(
        t0.sort_values("target"),
        prices[["isin", "date", "close"]],
        left_on="target",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p0")
    
    p1 = pd.merge_asof(
        t1.sort_values("target"),
        prices[["isin", "date", "close"]],
        left_on="target",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p1")
    
    df = pd.concat([p0, p1], axis=1)
    
    # Return percentage
    fwd_ret = (df["p1"] / df["p0"]) - 1.0
    return fwd_ret.replace([np.inf, -np.inf], np.nan)


def compute_decile_report(
    ctx: FactorContext,
    factor_id: str,
    index_name: str,
    start_date: date,
    end_date: date,
    eval_freq_days: int = 21,
) -> pd.DataFrame:
    """Compute a decile spread report for a factor.
    
    Evaluates the factor historically, sorts universe into deciles,
    and calculates forward returns.
    
    Args:
        ctx: The FactorContext for data access.
        factor_id: The ID of the factor to evaluate (must exist in registry).
        index_name: The index to use as the universe (e.g. 'NIFTY 50').
        start_date: Start of backtest.
        end_date: End of backtest.
        eval_freq_days: How often to rebalance and measure forward returns (e.g. 21 days = ~1 month).
        
    Returns:
        DataFrame with decile statistics.
    """
    if factor_id not in registry._factors:
        raise ValueError(f"Factor '{factor_id}' not found in registry.")
        
    meta = registry._factors[factor_id]
    func = meta.func
    direction = meta.direction
    
    # Generate evaluation dates
    dates = pd.date_range(start_date, end_date, freq=f"{eval_freq_days}D").date
    
    results = []
    
    for dt in dates:
        logger.debug("evaluating_factor_dt", factor=factor_id, dt=dt.isoformat())
        
        # 1. Compute Factor on entire available universe
        scores = func(ctx, dt)
        if scores.empty:
            continue
            
        # 2. Get Universe (PIT index constituents)
        if index_name.upper() == "ALL":
            # Use all available scores
            isins = scores.index.tolist()
        else:
            from indiquant.store.pit import index_constituents
            constituents = index_constituents(ctx.lakehouse, index_name, dt)
            if constituents.empty:
                continue
            isins = constituents["isin"].tolist()
            
        scores = scores.reindex(isins).dropna()
        if len(scores) < 10:
            # Need at least 10 stocks for deciles
            continue
            
        # 3. Fetch Forward Returns
        valid_isins = scores.index.tolist()
        fwd_returns = _get_forward_returns(ctx, valid_isins, dt, forward_days=eval_freq_days)
        
        # Combine
        df = pd.DataFrame({"score": scores, "fwd_ret": fwd_returns}).dropna()
        if len(df) < 10:
            continue
            
        # 4. Rank and Decile
        # direction=1 means higher is better (Decile 1)
        # direction=-1 means lower is better (Decile 1)
        # We want rank 1 to be the "best". 
        ascending = (direction == -1)
        
        df["rank"] = df["score"].rank(method="first", ascending=ascending)
        
        # pd.qcut creates deciles 1-10 based on the rank
        try:
            df["decile"] = pd.qcut(df["rank"], 10, labels=range(1, 11))
        except ValueError:
            # Can fail if there are many duplicate ranks, but method='first' prevents this.
            continue
            
        # 5. Calculate IC (Spearman Rank Correlation between Score and Forward Return)
        # Because we want positive IC to mean "factor worked as intended", 
        # we adjust the sign by direction.
        ic = df["score"].corr(df["fwd_ret"], method="spearman") * (1 if direction == 1 else -1)
        
        # Aggregate returns per decile
        decile_returns = df.groupby("decile", observed=True)["fwd_ret"].mean()
        
        # Record
        row = {
            "date": dt,
            "ic": ic,
            "universe_size": len(df),
        }
        for d in range(1, 11):
            row[f"D{d}"] = decile_returns.get(d, np.nan)
            
        results.append(row)
        
    if not results:
        return pd.DataFrame()
        
    res_df = pd.DataFrame(results).set_index("date")
    
    # Calculate Summary Averages across all dates
    summary = res_df.mean()
    
    # Calculate Top-Bottom Spread (D1 - D10)
    summary["Spread (D1-D10)"] = summary["D1"] - summary["D10"]
    
    # Monotonicity score (correlation of decile number with its return)
    # Perfectly monotonic: D1 > D2 > ... > D10. Decile array [1,2,3...10].
    # So if monotonic, correlation should be -1.0. We flip it so +1 is perfect.
    decile_means = summary[[f"D{d}" for d in range(1, 11)]].values
    monotonicity = -pd.Series(range(1, 11)).corr(pd.Series(decile_means), method="spearman")
    
    summary["Monotonicity"] = monotonicity
    
    # Convert returns to percentage
    for col in summary.index:
        if col.startswith("D") or col == "Spread (D1-D10)":
            summary[col] = summary[col] * 100.0
            
    return summary
