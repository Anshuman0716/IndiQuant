"""Validation and Anti-Overfitting Harness."""

from .bootstrap import extract_percentile_paths, stationary_block_bootstrap
from .deflated_sharpe import deflated_sharpe_ratio, expected_maximum_sharpe, min_backtest_length
from .multiple_testing import romano_wolf_stepdown
from .pbo import compute_pbo
from .registry import TrialRegistry, record_run

__all__ = [
    "TrialRegistry",
    "compute_pbo",
    "deflated_sharpe_ratio",
    "expected_maximum_sharpe",
    "extract_percentile_paths",
    "min_backtest_length",
    "record_run",
    "romano_wolf_stepdown",
    "stationary_block_bootstrap",
]
