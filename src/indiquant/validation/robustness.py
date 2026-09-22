"""Robustness suite for evaluating backtests."""
from typing import Callable, Dict, Any, List
import pandas as pd
import numpy as np
import structlog
from datetime import date

logger = structlog.get_logger(__name__)


def run_regime_slicing(returns: pd.Series) -> pd.DataFrame:
    """Evaluate performance in specific historical regimes."""
    regimes = {
        "Taper Tantrum (2013)": (date(2013, 5, 22), date(2013, 8, 30)),
        "Correction (2015-16)": (date(2015, 3, 3), date(2016, 2, 29)),
        "Smallcap Rally (2017)": (date(2017, 1, 1), date(2017, 12, 31)),
        "IL&FS Crash (2018)": (date(2018, 1, 1), date(2018, 12, 31)),
        "COVID Crash (Mar 2020)": (date(2020, 2, 19), date(2020, 3, 23)),
        "Post-COVID Bull (2020-21)": (date(2020, 4, 1), date(2021, 10, 18)),
        "Drawdown (2022)": (date(2021, 10, 19), date(2022, 6, 17)),
        "Smallcap Rally (2023-24)": (date(2023, 3, 28), date(2024, 2, 29))
    }
    
    results = []
    
    for name, (start, end) in regimes.items():
        slice_idx = (returns.index >= pd.Timestamp(start)) & (returns.index <= pd.Timestamp(end))
        slice_ret = returns.loc[slice_idx]
        
        if len(slice_ret) < 10:
            continue
            
        cagr = (slice_ret.add(1).prod() ** (252 / len(slice_ret)) - 1) * 100
        sharpe = slice_ret.mean() / slice_ret.std() * np.sqrt(252) if slice_ret.std() > 0 else 0
        
        results.append({
            "Regime": name,
            "Days": len(slice_ret),
            "CAGR": cagr,
            "Sharpe": sharpe
        })
        
    return pd.DataFrame(results)


def factor_attribution(
    strategy_returns: pd.Series,
    factor_returns: pd.DataFrame
) -> pd.DataFrame:
    """Regress strategy returns on market, size, value, momentum factors.
    
    Returns alpha, betas, and t-stats.
    """
    import statsmodels.api as sm
    
    aligned = pd.concat([strategy_returns.rename("strategy"), factor_returns], axis=1).dropna()
    if len(aligned) < 30:
        return pd.DataFrame()
        
    Y = aligned["strategy"]
    X = aligned.drop(columns=["strategy"])
    X = sm.add_constant(X)
    
    model = sm.OLS(Y, X).fit()
    
    res = pd.DataFrame({
        "coef": model.params,
        "tstat": model.tvalues,
        "pval": model.pvalues
    })
    
    # Annualize alpha assuming daily returns
    if "const" in res.index:
        res.loc["const", "coef_annual"] = res.loc["const", "coef"] * 252
        
    return res


def run_null_control(
    strategy_returns: pd.Series,
    n_permutations: int = 1000
) -> Dict[str, Any]:
    """Run pipeline on shuffled returns and synthetic GBM series."""
    n = len(strategy_returns)
    mu = strategy_returns.mean()
    sigma = strategy_returns.std()
    
    # 1. Shuffled returns
    shuffled_sharpes = []
    vals = strategy_returns.values
    for _ in range(n_permutations // 2):
        np.random.shuffle(vals)
        sr = np.mean(vals) / np.std(vals) * np.sqrt(252)
        shuffled_sharpes.append(sr)
        
    # 2. Synthetic GBM
    gbm_sharpes = []
    for _ in range(n_permutations // 2):
        # Generate log-normal daily returns with matching mean/std
        synth = np.random.normal(mu, sigma, n)
        sr = np.mean(synth) / np.std(synth) * np.sqrt(252)
        gbm_sharpes.append(sr)
        
    null_sharpes = np.array(shuffled_sharpes + gbm_sharpes)
    orig_sr = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
    
    p_val = np.mean(null_sharpes >= orig_sr)
    
    return {
        "orig_sharpe": orig_sr,
        "null_sharpe_mean": np.mean(null_sharpes),
        "null_sharpe_95": np.percentile(null_sharpes, 95),
        "p_value": p_val,
        "shuffled_sharpes": shuffled_sharpes,
        "gbm_sharpes": gbm_sharpes
    }
