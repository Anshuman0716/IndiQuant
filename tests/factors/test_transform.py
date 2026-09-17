"""Tests for cross-sectional factor transformations."""

import numpy as np
import pandas as pd
import pytest

from indiquant.factors.transform import rank_normalize, winsorize, z_score


def test_winsorize_symmetry() -> None:
    """Test that winsorize symmetrically clips extreme values.
    
    A synthetic uniform distribution with extreme outliers.
    """
    # 1 to 100 perfectly uniform
    data = list(range(1, 101))
    
    # Add huge outliers at both ends
    data[0] = -10000  # Extreme low
    data[-1] = 10000  # Extreme high
    
    s = pd.Series(data)
    
    # Winsorize at 5% (clip bottom 5 and top 5)
    # The 5th percentile of 1..100 (where 0th is -10000, 1st is 2, etc.)
    # Pandas quantile(0.05) on 100 items will be around the 5th item.
    w = winsorize(s, limits=(0.05, 0.05))
    
    # The minimum value should no longer be -10000, it should be clipped to the 5th percentile
    assert w.min() > -10000
    assert w.min() == s.quantile(0.05)
    
    # The maximum value should no longer be 10000, it should be clipped to the 95th percentile
    assert w.max() < 10000
    assert w.max() == s.quantile(0.95)
    
    # Middle values remain unchanged
    assert w[50] == s[50]


def test_winsorize_handles_nans() -> None:
    """Winsorize must ignore NaNs when finding bounds and preserve them in output."""
    s = pd.Series([1.0, 2.0, np.nan, 100.0, 101.0, np.nan])
    w = winsorize(s, limits=(0.25, 0.25))
    
    # NaNs remain NaNs
    assert pd.isna(w.iloc[2])
    assert pd.isna(w.iloc[5])
    
    # 25th percentile of [1, 2, 100, 101] is 1.75
    # 75th percentile of [1, 2, 100, 101] is 100.25
    assert w.iloc[0] == 1.75  # 1.0 is clipped up to 1.75
    assert w.iloc[4] == 100.25 # 101.0 is clipped down to 100.25


def test_z_score() -> None:
    """Z-score normalizes to mean 0, std 1."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = z_score(s)
    
    assert np.isclose(z.mean(), 0.0)
    assert np.isclose(z.std(), 1.0)
    
    # Value 3.0 is exactly the mean
    assert z.iloc[2] == 0.0


def test_z_score_grouped() -> None:
    """Z-score with group_by computes metrics within each group."""
    # Two distinct groups with very different means
    # Group A: mean 10, std ~1.58
    # Group B: mean 100, std ~15.8
    s = pd.Series([8.0, 10.0, 12.0, 80.0, 100.0, 120.0])
    g = pd.Series(["A", "A", "A", "B", "B", "B"])
    
    z = z_score(s, group_by=g)
    
    # 10 is the mean of group A, 100 is the mean of group B
    assert z.iloc[1] == 0.0
    assert z.iloc[4] == 0.0
    
    # Values below their group mean are negative
    assert z.iloc[0] < 0.0
    assert z.iloc[3] < 0.0
    
    # Values above their group mean are positive
    assert z.iloc[2] > 0.0
    assert z.iloc[5] > 0.0


def test_rank_normalize() -> None:
    """Rank normalize scales to exactly [0, 1]."""
    s = pd.Series([10.0, 50.0, 20.0, np.nan, 30.0])
    r = rank_normalize(s)
    
    # 10 -> rank 1 (min) -> 0.0
    # 20 -> rank 2 -> 0.333
    # 30 -> rank 3 -> 0.666
    # 50 -> rank 4 (max) -> 1.0
    
    assert r.iloc[0] == 0.0
    assert r.iloc[1] == 1.0
    assert np.isclose(r.iloc[2], 1/3)
    assert pd.isna(r.iloc[3])
