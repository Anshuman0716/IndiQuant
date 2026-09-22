"""Portfolio weighting and allocation schemes."""

import numpy as np
import pandas as pd


def equal_weight(universe: list[str]) -> pd.Series:
    """Assign equal weight to all assets in the universe."""
    if not universe:
        return pd.Series(dtype=float)
    w = 1.0 / len(universe)
    return pd.Series(w, index=universe)


def inverse_vol_weight(volatilities: pd.Series) -> pd.Series:
    """Weight inversely proportional to historical volatility."""
    if volatilities.empty:
        return pd.Series(dtype=float)
    inv_vol = 1.0 / volatilities
    return inv_vol / inv_vol.sum()


def score_weight(scores: pd.Series, exponent: float = 1.0) -> pd.Series:
    """Weight proportional to factor scores (must be positive)."""
    if scores.empty:
        return pd.Series(dtype=float)
    if (scores < 0).any():
        raise ValueError("Scores must be positive for score weighting.")
    w = scores ** exponent
    return w / w.sum()


def capped_market_cap_weight(
    mcaps: pd.Series, 
    cap_pct: float = 0.10
) -> pd.Series:
    """Market cap weighting with a maximum position cap."""
    if mcaps.empty:
        return pd.Series(dtype=float)
        
    weights = mcaps / mcaps.sum()
    
    # Iteratively cap weights and redistribute the excess
    while (weights > cap_pct + 1e-6).any():
        capped_mask = weights > cap_pct
        excess = (weights[capped_mask] - cap_pct).sum()
        
        weights[capped_mask] = cap_pct
        
        # Redistribute excess proportionally among non-capped assets
        uncapped = weights[~capped_mask]
        if uncapped.sum() > 0:
            weights[~capped_mask] += excess * (uncapped / uncapped.sum())
        else:
            # If all are capped (e.g. universe < 10 and cap is 10%), break to avoid infinite loop
            break
            
    return weights / weights.sum()
