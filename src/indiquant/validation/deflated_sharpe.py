"""Deflated Sharpe Ratio (Bailey & López de Prado)."""
import numpy as np
import scipy.stats as stats
import pandas as pd

def expected_maximum_sharpe(n_trials: int, mean_sharpe: float = 0.0, var_sharpe: float = 1.0) -> float:
    """Calculate the expected maximum Sharpe ratio for a given number of trials."""
    if n_trials <= 1:
        return mean_sharpe
        
    # Approximation of the expected maximum of standard normal random variables
    emc = 0.5772156649 # Euler-Mascheroni constant
    max_z = (1 - emc) * stats.norm.ppf(1 - 1.0 / n_trials) + emc * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    
    return mean_sharpe + np.sqrt(var_sharpe) * max_z

def deflated_sharpe_ratio(
    observed_sharpe: float,
    returns: pd.Series,
    n_trials: int,
    mean_sharpe_trials: float = 0.0,
    var_sharpe_trials: float = 1.0 / 252.0,
    annualization_factor: int = 252
) -> float:
    """Calculate the Deflated Sharpe Ratio (DSR)."""
    # Annualized properties
    n = len(returns)
    skew = returns.skew()
    kurt = returns.kurtosis()
    
    sr = observed_sharpe / np.sqrt(annualization_factor)
    
    # Expected maximum Sharpe across all trials
    sr0 = expected_maximum_sharpe(n_trials, mean_sharpe_trials, var_sharpe_trials)
    
    # Bailey & López de Prado Variance of Sharpe Ratio
    sr_var = (1 - (skew * sr) + ((kurt - 1) / 4) * (sr ** 2)) / (n - 1)
    
    if sr_var <= 0:
        return 0.0
        
    # DSR is the CDF of the true SR being greater than the expected max SR
    z_score = (sr - sr0) / np.sqrt(sr_var)
    dsr = stats.norm.cdf(z_score)
    
    return dsr

def min_backtest_length(
    target_sharpe: float,
    mean_sharpe_trials: float = 0.0,
    var_sharpe_trials: float = 1.0 / 252.0,
    n_trials: int = 1,
    skew: float = 0.0,
    kurt: float = 3.0,
    annualization_factor: int = 252
) -> float:
    """Minimum Backtest Length (MinBTL)."""
    sr0 = expected_maximum_sharpe(n_trials, mean_sharpe_trials, var_sharpe_trials)
    
    # We want Z >= 2 (approx 97.5% confidence) for sr > sr0
    if target_sharpe <= sr0 * np.sqrt(annualization_factor):
        return np.inf
        
    sr = target_sharpe / np.sqrt(annualization_factor)
    sr0 = sr0
    
    # Solve for n where z = (sr - sr0) / sqrt(var) = 2
    # var = (1 - skew*sr + (kurt-1)/4 * sr^2) / (n-1)
    numerator = 1 - (skew * sr) + ((kurt - 1) / 4) * (sr ** 2)
    denominator = ((sr - sr0) / 2.0) ** 2
    
    n_min = 1 + numerator / denominator
    return n_min / annualization_factor # returns in years
