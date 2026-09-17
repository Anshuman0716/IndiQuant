"""Tests for composite score logic."""

import numpy as np
import pandas as pd

from indiquant.factors.composite import compute_composite_score


def test_compute_composite_score_perfect() -> None:
    """A perfect score across all pillars yields 100."""
    scores = pd.DataFrame({
        "QUALITY": [1.0],
        "VALUATION": [1.0],
        "GROWTH": [1.0],
        "HEALTH": [1.0],
        "MOMENTUM": [1.0],
        "OWNERSHIP": [1.0],
    }, index=["INE123"])
    
    res = compute_composite_score(scores, min_pillars_required=6)
    assert res.iloc[0] == 100.0


def test_compute_composite_score_reweighting() -> None:
    """Missing pillars cause weights to be rescaled."""
    # Suppose QUALITY (0.25) and VALUATION (0.20) are the only ones present.
    # Total weight = 0.45.
    # If a stock has 1.0 in QUALITY and 0.0 in VALUATION:
    # Weighted sum = 1.0 * 0.25 + 0.0 * 0.20 = 0.25
    # Normalized sum = 0.25 / 0.45 = 0.5555...
    # Final score = 55.55...
    
    scores = pd.DataFrame({
        "QUALITY": [1.0],
        "VALUATION": [0.0],
        "GROWTH": [np.nan],
        "HEALTH": [np.nan],
        "MOMENTUM": [np.nan],
        "OWNERSHIP": [np.nan],
    }, index=["INE123"])
    
    res = compute_composite_score(scores, min_pillars_required=2)
    assert np.isclose(res.iloc[0], 55.555555)


def test_compute_composite_score_pillar_floor() -> None:
    """Stocks not meeting the min_pillars_required threshold are dropped (NaN)."""
    scores = pd.DataFrame({
        "QUALITY": [1.0, 1.0],
        "VALUATION": [1.0, np.nan],
        "GROWTH": [1.0, np.nan],
        "HEALTH": [1.0, np.nan],
        "MOMENTUM": [np.nan, np.nan],
        "OWNERSHIP": [np.nan, np.nan],
    }, index=["STOCK_4_PILLARS", "STOCK_1_PILLAR"])
    
    res = compute_composite_score(scores, min_pillars_required=4)
    
    assert res.loc["STOCK_4_PILLARS"] == 100.0
    assert pd.isna(res.loc["STOCK_1_PILLAR"])
