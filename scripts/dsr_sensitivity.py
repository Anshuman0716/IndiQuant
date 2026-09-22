"""Script to compute DSR sensitivity analysis."""

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from indiquant.validation.deflated_sharpe import expected_maximum_sharpe, deflated_sharpe_ratio

console = Console()

# Assume we have 5 years of daily returns (1260 days)
np.random.seed(42)
# Generate a series with SR approx 1.2
# Daily SR = 1.2 / sqrt(252) = 0.0755
n_samples = 1260
daily_sr = 1.2 / np.sqrt(252)
returns = pd.Series(np.random.normal(loc=daily_sr * 0.01, scale=0.01, size=n_samples))
# Ensure exact SR
current_sr = (returns.mean() / returns.std()) * np.sqrt(252)
adjustment = (1.2 / np.sqrt(252)) - (returns.mean() / returns.std())
returns = returns + (adjustment * returns.std())

observed_sharpe = 1.2
trials = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]

console.print(f"[bold cyan]DSR Sensitivity Analysis (Observed Annualized Sharpe = {observed_sharpe})[/bold cyan]")

t = Table()
t.add_column("Assumed Trial Count")
t.add_column("Expected Max SR (sr0)")
t.add_column("Deflated Sharpe Ratio (DSR)")

for n_trials in trials:
    dsr = deflated_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        returns=returns,
        n_trials=n_trials,
        annualization_factor=252
    )
    sr0 = expected_maximum_sharpe(n_trials, var_sharpe=1.0/252.0) * np.sqrt(252)
    t.add_row(str(n_trials), f"{sr0:.2f}", f"{dsr:.4f}")

console.print(t)

# Find crossing points exactly
def find_crossing(target_dsr):
    # Binary search over trials
    low = 1
    high = 1000000
    while low < high:
        mid = (low + high) // 2
        dsr = deflated_sharpe_ratio(observed_sharpe, returns, mid, annualization_factor=252)
        if dsr < target_dsr:
            high = mid
        else:
            low = mid + 1
    return low

console.print(f"DSR crosses below 0.95 at trial count: {find_crossing(0.95)}")
console.print(f"DSR crosses below 0.90 at trial count: {find_crossing(0.90)}")
console.print(f"DSR crosses below 0.50 at trial count: {find_crossing(0.50)}")
