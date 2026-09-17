"""Cross-sectional transformations for factors.

Provides winsorization, z-scoring, and rank normalization.
"""

import numpy as np
import pandas as pd


def winsorize(series: pd.Series, limits: tuple[float, float] = (0.01, 0.01)) -> pd.Series:
    """Winsorize a series by clipping extreme values.
    
    Args:
        series: The factor values to winsorize.
        limits: Tuple of (lower_percentile, upper_percentile) to cut off.
                e.g., (0.01, 0.01) clips at the 1st and 99th percentiles.
                
    Returns:
        Winsorized series with NaNs preserved.
    """
    if series.empty or series.isna().all():
        return series.copy()

    lower_pct, upper_pct = limits
    if not (0 <= lower_pct < 0.5 and 0 <= upper_pct < 0.5):
        raise ValueError("Winsorize limits must be between 0 and 0.5")

    # Calculate quantiles ignoring NaNs
    lower_bound = series.quantile(lower_pct)
    upper_bound = series.quantile(1.0 - upper_pct)

    # Clip values. NaNs remain NaN.
    return series.clip(lower=lower_bound, upper=upper_bound)


def z_score(series: pd.Series, group_by: pd.Series | None = None) -> pd.Series:
    """Compute the cross-sectional z-score of a series.
    
    (x - mean) / std. NaNs are ignored in the calculation and preserved.
    
    Args:
        series: The factor values to z-score.
        group_by: Optional series of the same length containing group labels 
                  (e.g., sectors). If provided, z-scores are calculated 
                  within each group.
                  
    Returns:
        Z-scored series.
    """
    if series.empty or series.isna().all():
        return series.copy()
        
    if group_by is not None:
        if len(series) != len(group_by):
            raise ValueError("group_by series must have the same length as the input series")
            
        def _group_z(x: pd.Series) -> pd.Series:
            if len(x.dropna()) < 2:
                # Need at least 2 points for std dev
                return pd.Series(0.0, index=x.index)
            std = x.std()
            if pd.isna(std) or std == 0:
                return pd.Series(0.0, index=x.index)
            return (x - x.mean()) / std

        # Combine into a temporary dataframe to align indices safely
        df = pd.DataFrame({"val": series, "group": group_by})
        # Apply group-wise z-score and return just the val column
        return df.groupby("group")["val"].transform(_group_z)

    # Global cross-sectional z-score
    std = series.std()
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
        
    return (series - series.mean()) / std


def rank_normalize(series: pd.Series) -> pd.Series:
    """Rank-normalize a series to the range [0, 1].
    
    Useful for creating uniform composite scores.
    """
    if series.empty or series.isna().all():
        return series.copy()
        
    ranks = series.rank(method="average", na_option="keep")
    min_rank = ranks.min()
    max_rank = ranks.max()
    
    if pd.isna(min_rank) or min_rank == max_rank:
        return pd.Series(0.5, index=series.index)
        
    return (ranks - min_rank) / (max_rank - min_rank)
