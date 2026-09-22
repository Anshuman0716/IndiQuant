"""Multiple testing corrections (White's Reality Check, Romano-Wolf)."""
import numpy as np
import pandas as pd

def romano_wolf_stepdown(
    returns_matrix: pd.DataFrame,
    benchmark_returns: pd.Series = None,
    n_bootstraps: int = 1000,
    block_size: int = 10
) -> pd.Series:
    """Romano-Wolf stepdown procedure for controlling Family-Wise Error Rate (FWER).
    
    Args:
        returns_matrix: DataFrame of shape (n_samples, n_strategies)
        benchmark_returns: Optional Series of shape (n_samples,)
        
    Returns:
        pd.Series of adjusted p-values for each strategy.
    """
    n_samples, n_strats = returns_matrix.shape
    
    # Calculate excess returns if benchmark is provided
    if benchmark_returns is not None:
        returns_matrix = returns_matrix.sub(benchmark_returns, axis=0)
        
    # Calculate empirical mean returns for each strategy
    mu_hat = returns_matrix.mean(axis=0).values
    
    # We will compute the t-statistics for the mean return being > 0
    std_hat = returns_matrix.std(axis=0).values / np.sqrt(n_samples)
    std_hat[std_hat == 0] = 1e-8
    t_hat = mu_hat / std_hat
    
    # Generate bootstrap indices
    boot_indices = np.zeros((n_samples, n_bootstraps), dtype=int)
    p = 1.0 / block_size
    
    for b in range(n_bootstraps):
        idx = 0
        while idx < n_samples:
            L = np.random.geometric(p)
            start_idx = np.random.randint(0, n_samples)
            take = min(L, n_samples - idx)
            
            end_idx = start_idx + take
            if end_idx <= n_samples:
                boot_indices[idx:idx+take, b] = np.arange(start_idx, end_idx)
            else:
                overflow = end_idx - n_samples
                boot_indices[idx:idx+take, b] = np.concatenate([
                    np.arange(start_idx, n_samples),
                    np.arange(0, overflow)
                ])[:take]
            idx += take
            
    # Bootstrap max t-statistics
    adj_p_values = np.zeros(n_strats)
    remaining_indices = list(range(n_strats))
    
    # Order strategies by decreasing original t-stat
    order = np.argsort(t_hat)[::-1]
    ordered_indices = [order[i] for i in range(n_strats)]
    
    last_p = 0.0
    
    for m in range(n_strats):
        current_strat_idx = ordered_indices[m]
        
        # Calculate bootstrapped centered t-statistics for remaining strategies
        boot_max_t = np.zeros(n_bootstraps)
        
        for b in range(n_bootstraps):
            idx = boot_indices[:, b]
            boot_returns = returns_matrix.iloc[idx, remaining_indices]
            
            # Center the bootstrapped returns by subtracting the empirical mean
            boot_centered = boot_returns - mu_hat[remaining_indices]
            
            boot_mu = boot_centered.mean(axis=0).values
            boot_std = boot_centered.std(axis=0).values / np.sqrt(n_samples)
            boot_std[boot_std == 0] = 1e-8
            
            boot_t = boot_mu / boot_std
            boot_max_t[b] = np.max(boot_t)
            
        # P-value is the fraction of times the bootstrapped max t-stat > original t-stat
        orig_t = t_hat[current_strat_idx]
        p_val = np.mean(boot_max_t >= orig_t)
        
        # Enforce monotonicity of adjusted p-values
        adj_p_val = max(last_p, p_val)
        adj_p_values[current_strat_idx] = adj_p_val
        last_p = adj_p_val
        
        # Remove current strategy from remaining set for next stepdown
        remaining_indices.remove(current_strat_idx)
        
    return pd.Series(adj_p_values, index=returns_matrix.columns)
