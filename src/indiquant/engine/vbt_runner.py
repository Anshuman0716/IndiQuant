"""VectorBT cross-sectional runner for baseline execution."""

import numpy as np
import pandas as pd
import vectorbt as vbt


def run_vbt_cross_sectional(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    freq: str = "D",
    init_cash: float = 1_000_000,
    fees: float = 0.0,
    slippage: float = 0.0,
) -> vbt.Portfolio:
    """Run a basic vectorbt backtest with target weights.
    
    Args:
        prices: DataFrame of close prices, index=dates, columns=assets.
        weights: DataFrame of target weights, index=dates, columns=assets.
        freq: Pandas frequency string.
        init_cash: Initial capital.
        fees: Flat fee rate (e.g. 0.001 for 0.1%).
        slippage: Flat slippage rate.
        
    Returns:
        vbt.Portfolio object.
    """
    # Align weights to prices. We forward fill weights so they hold until next rebalance.
    aligned_weights = weights.reindex(prices.index, method="ffill").fillna(0.0)
    
    pf = vbt.Portfolio.from_orders(
        close=prices,
        size=aligned_weights,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        freq=freq,
    )
    return pf
