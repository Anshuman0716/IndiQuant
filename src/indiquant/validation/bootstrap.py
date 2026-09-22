"""Stationary block bootstrap for strategy returns."""
import numpy as np
import pandas as pd
from typing import Dict

def stationary_block_bootstrap(
    returns: pd.Series,
    block_size: int = 10,
    n_paths: int = 1000
) -> pd.DataFrame:
    """Generate bootstrap paths using stationary block bootstrap."""
    n_samples = len(returns)
    paths = np.zeros((n_samples, n_paths))
    ret_vals = returns.values
    
    # Geometric distribution for block lengths in stationary block bootstrap
    p = 1.0 / block_size
    
    for i in range(n_paths):
        idx = 0
        while idx < n_samples:
            # Draw block length
            L = np.random.geometric(p)
            # Draw start index
            start_idx = np.random.randint(0, n_samples)
            
            # Extract block with wrapping
            end_idx = start_idx + L
            if end_idx <= n_samples:
                block = ret_vals[start_idx:end_idx]
            else:
                overflow = end_idx - n_samples
                block = np.concatenate([ret_vals[start_idx:], ret_vals[:overflow]])
                
            # Place in path
            remaining = n_samples - idx
            take = min(L, remaining)
            paths[idx:idx+take, i] = block[:take]
            idx += take
            
    return pd.DataFrame(paths, index=returns.index)

def extract_percentile_paths(paths: pd.DataFrame) -> Dict[str, pd.Series]:
    """Extract cumulative percentile equity paths from bootstrapped returns."""
    cum_returns = (1 + paths).cumprod()
    
    percentiles = [5, 25, 50, 75, 95]
    results = {}
    
    for p in percentiles:
        results[f"p{p}"] = cum_returns.quantile(p / 100.0, axis=1)
        
    return results
