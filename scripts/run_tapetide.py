"""Generate real metrics for the full report."""
from datetime import date
import pandas as pd
import numpy as np
from rich.console import Console

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext
import indiquant.factors.growth
import indiquant.factors.value
import indiquant.factors.volatility
import indiquant.factors.microstructure
import indiquant.factors.quality
import indiquant.factors.momentum

from indiquant.strategies.tapetide_composite import generate_tapetide_composite_weights
from indiquant.engine.execution import ExecutionModel
from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints
from indiquant.engine.event_loop import run_event_loop

console = Console()

def run_actual_backtest():
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    ctx = FactorContext(lakehouse)
    
    start_date = date(2022, 1, 1)
    end_date = date(2024, 12, 31)
    
    console.print("Generating weights for Tapetide Composite...")
    weights = generate_tapetide_composite_weights(ctx, start_date, end_date, index_name="ALL", rebalance_freq="ME", top_n=10)
    
    if weights.empty:
        console.print("[red]No weights generated![/red]")
        return None
        
    prices = ctx.get_prices(end_date, lookback_days=1000)
    prices = prices[pd.to_datetime(prices["date"]).dt.date >= start_date]
    
    prices_dates = pd.to_datetime(prices["date"].unique()).sort_values()
    weights.index = pd.to_datetime(weights.index)
    all_dates = prices_dates.union(weights.index).sort_values()
    aligned_weights = weights.reindex(all_dates).ffill().reindex(prices_dates).fillna(0.0)
    
    mi_prices = prices.set_index(["date", "isin"]).sort_index()
    
    # Run once to get baseline returns
    statutory_real = StatutoryCostModel(brokerage_rate=0.0001, flat_brokerage=20.0)
    slippage_real = SlippageModel(impact_c=1.0)
    constraints_real = ExecutionConstraints(enforce_circuits=True, settlement_t_plus=1, enforce_whole_shares=True)
    exec_real = ExecutionModel(statutory_real, slippage_real, constraints_real, fill_price="CLOSE")
    
    console.print("Running event loop...")
    el_real = run_event_loop(mi_prices, aligned_weights, exec_real, init_cash=1000000.0)
    
    returns = el_real["portfolio_value"].pct_change().dropna()
    sr = (returns.mean() / returns.std()) * np.sqrt(252)
    cagr = ((el_real["portfolio_value"].iloc[-1] / el_real["portfolio_value"].iloc[0]) ** (252 / len(returns)) - 1) * 100
    
    console.print(f"Base SR: {sr:.2f}, CAGR: {cagr:.2f}%")
    
    # Save objects for further tests
    return returns, mi_prices, aligned_weights, exec_real

if __name__ == "__main__":
    res = run_actual_backtest()
    if res:
        ret, _, _, _ = res
        ret.to_csv("actual_tapetide_returns.csv")
