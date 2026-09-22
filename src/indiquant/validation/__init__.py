"""Validation and Anti-Overfitting Harness."""

from .registry import TrialRegistry, record_run
from .deflated_sharpe import expected_maximum_sharpe, deflated_sharpe_ratio, min_backtest_length
from .pbo import compute_pbo
from .bootstrap import stationary_block_bootstrap, extract_percentile_paths
from .multiple_testing import romano_wolf_stepdown

__all__ = [
    "TrialRegistry", "record_run",
    "expected_maximum_sharpe", "deflated_sharpe_ratio", "min_backtest_length",
    "compute_pbo",
    "stationary_block_bootstrap", "extract_percentile_paths",
    "romano_wolf_stepdown"
]
