"""Cross-validation splits with purging and embargo."""
import itertools
from typing import List, Tuple
import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def check_sealed_period(dates: pd.DatetimeIndex, unseal: bool = False, sealed_years: int = 2) -> pd.DatetimeIndex:
    """Enforce a sealed out-of-sample period."""
    if len(dates) == 0:
        return dates
        
    latest_date = dates.max()
    cutoff_date = latest_date - pd.DateOffset(years=sealed_years)
    
    if unseal:
        logger.warning("sealed_period_unsealed", cutoff=cutoff_date.date())
        return dates
        
    logger.info("enforcing_sealed_period", cutoff=cutoff_date.date())
    return dates[dates <= cutoff_date]


def walk_forward_splits(
    dates: pd.DatetimeIndex, 
    train_size: int, 
    test_size: int, 
    expanding: bool = False
) -> List[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Walk-forward train/test splits."""
    dates = np.sort(dates.unique())
    splits = []
    
    start_idx = 0
    while start_idx + train_size + test_size <= len(dates):
        if expanding:
            train_dates = dates[: start_idx + train_size]
        else:
            train_dates = dates[start_idx : start_idx + train_size]
            
        test_dates = dates[start_idx + train_size : start_idx + train_size + test_size]
        splits.append((train_dates, test_dates))
        start_idx += test_size
        
    return splits


def purged_kfold_splits(
    dates: pd.DatetimeIndex,
    k: int = 5,
    embargo_pct: float = 0.01,
    purge_periods: int = 0
) -> List[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Purged K-Fold Cross Validation with Embargo (López de Prado)."""
    dates = np.sort(dates.unique())
    n_samples = len(dates)
    fold_size = n_samples // k
    embargo_size = int(n_samples * embargo_pct)
    
    splits = []
    for i in range(k):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < k - 1 else n_samples
        
        test_dates = dates[test_start:test_end]
        
        # Purge before test
        train_before_end = max(0, test_start - purge_periods)
        train_before = dates[:train_before_end]
        
        # Embargo after test
        train_after_start = min(n_samples, test_end + embargo_size)
        train_after = dates[train_after_start:]
        
        train_dates = np.concatenate([train_before, train_after])
        splits.append((pd.DatetimeIndex(train_dates), pd.DatetimeIndex(test_dates)))
        
    return splits


def cpcv_splits(
    dates: pd.DatetimeIndex,
    n_groups: int = 6,
    k_test: int = 2
) -> List[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Combinatorial Purged Cross-Validation (CPCV)."""
    dates = np.sort(dates.unique())
    n_samples = len(dates)
    group_size = n_samples // n_groups
    
    groups = []
    for i in range(n_groups):
        start = i * group_size
        end = (i + 1) * group_size if i < n_groups - 1 else n_samples
        groups.append(dates[start:end])
        
    # Generate all combinations of k_test groups
    import itertools
    combinations = list(itertools.combinations(range(n_groups), k_test))
    
    splits = []
    for test_idx in combinations:
        test_dates = np.concatenate([groups[i] for i in test_idx])
        train_dates = np.concatenate([groups[i] for i in range(n_groups) if i not in test_idx])
        
        # In a strict CPCV, we would also purge boundaries here.
        # For this reference implementation, we just return the raw partitioned dates.
        splits.append((pd.DatetimeIndex(train_dates), pd.DatetimeIndex(test_dates)))
        
    return splits
