"""Probability of Backtest Overfitting (PBO)."""
import numpy as np
import pandas as pd
from typing import Dict, Tuple

def compute_pbo(
    performance_matrix: pd.DataFrame, 
    n_partitions: int = 4
) -> Tuple[float, np.ndarray]:
    """Compute Probability of Backtest Overfitting using CSCV.
    
    Args:
        performance_matrix: DataFrame of shape (n_strategies, n_samples) containing returns.
        n_partitions: Number of partitions for cross-validation (typically even).
        
    Returns:
        PBO (float): Probability of backtest overfitting.
        logits (np.ndarray): Distribution of logits for plotting.
    """
    n_strats, n_samples = performance_matrix.shape
    if n_strats < 2:
        return 0.0, np.array([])
        
    part_size = n_samples // n_partitions
    
    # Split returns into partitions
    partitions = []
    for i in range(n_partitions):
        start = i * part_size
        end = (i + 1) * part_size if i < n_partitions - 1 else n_samples
        partitions.append(performance_matrix.iloc[:, start:end])
        
    # Generate all combinations of n_partitions / 2
    import itertools
    combinations = list(itertools.combinations(range(n_partitions), n_partitions // 2))
    
    logits = []
    
    for train_idx in combinations:
        test_idx = [i for i in range(n_partitions) if i not in train_idx]
        
        # Train IS performance (e.g. Sharpe)
        train_returns = pd.concat([partitions[i] for i in train_idx], axis=1)
        train_sharpe = train_returns.mean(axis=1) / train_returns.std(axis=1).replace(0, 1e-8)
        
        # Test OOS performance
        test_returns = pd.concat([partitions[i] for i in test_idx], axis=1)
        test_sharpe = test_returns.mean(axis=1) / test_returns.std(axis=1).replace(0, 1e-8)
        
        # Find best IS strategy
        best_is_idx = train_sharpe.idxmax()
        
        # Rank of the best IS strategy in the OOS set
        test_ranks = test_sharpe.rank(ascending=True) # 1 is worst, n_strats is best
        rank_oos = test_ranks.loc[best_is_idx]
        
        # Relative rank (0 to 1)
        w_c = rank_oos / (n_strats + 1)
        
        # Logit
        logit = np.log(w_c / (1 - w_c))
        logits.append(logit)
        
    logits = np.array(logits)
    pbo = np.mean(logits < 0)
    
    return float(pbo), logits
