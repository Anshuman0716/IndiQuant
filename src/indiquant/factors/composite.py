"""Composite scoring logic (Tapetide Score)."""

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Default weights for the Tapetide Score
DEFAULT_WEIGHTS = {
    "QUALITY": 0.25,
    "VALUATION": 0.20,
    "GROWTH": 0.15,
    "HEALTH": 0.15,
    "MOMENTUM": 0.15,
    "OWNERSHIP": 0.10,
}


def compute_composite_score(
    pillar_scores: pd.DataFrame,
    weights: dict[str, float] | None = None,
    min_pillars_required: int = 4,
) -> pd.Series:
    """Compute the weighted composite Tapetide Score [0-100].
    
    Args:
        pillar_scores: DataFrame where columns are pillar names and rows are ISINs.
                       Values should be rank-normalized in [0, 1].
        weights: Dictionary of pillar weights. Defaults to DEFAULT_WEIGHTS.
        min_pillars_required: The 'pillar-floor' logic. If an ISIN has fewer than
                              this many valid pillars, its composite score is NaN.
                              
    Returns:
        Series of composite scores scaled to [0, 100].
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
        
    # Ensure columns match expected pillars
    available_pillars = [p for p in weights.keys() if p in pillar_scores.columns]
    if not available_pillars:
        return pd.Series(index=pillar_scores.index, dtype=float)

    # Count valid (non-NaN) pillars per row
    valid_counts = pillar_scores[available_pillars].notna().sum(axis=1)

    # Align weights to a series
    weight_series = pd.Series(weights)[available_pillars]
    
    # We want to re-weight based on available pillars.
    # For each row, sum the weights of non-NaN pillars.
    # If a row has NaNs, the remaining pillars carry proportionately more weight.
    
    # Create a boolean mask of valid data (1 if valid, 0 if NaN)
    valid_mask = pillar_scores[available_pillars].notna().astype(float)
    
    # Calculate the sum of weights for the valid pillars in each row
    row_weight_sums = (valid_mask * weight_series).sum(axis=1)
    
    # Calculate the weighted sum of the scores
    # .fillna(0) is safe here because the valid_mask nullifies the weight anyway
    weighted_sum = (pillar_scores[available_pillars].fillna(0) * weight_series).sum(axis=1)
    
    # Normalize by the row's weight sum to get a [0, 1] score
    final_score = weighted_sum / row_weight_sums
    
    # Scale to 0-100
    final_score = final_score * 100.0
    
    # Apply pillar-floor logic: mask out rows with too few valid pillars
    final_score = final_score.where(valid_counts >= min_pillars_required, pd.NA)
    
    return final_score.astype(float)
