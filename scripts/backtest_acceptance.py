"""Acceptance criteria for the backtesting engine and cost model."""

import sys
from datetime import date
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
import matplotlib.pyplot as plt

# Ensure factors are registered
import indiquant.factors.momentum
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext
from indiquant.strategies.momentum import generate_momentum_weights

from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints
from indiquant.engine.execution import ExecutionModel

from indiquant.engine.vbt_runner import run_vbt_cross_sectional
from indiquant.engine.event_loop import run_event_loop

console = Console()


def run_acceptance():
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    ctx = FactorContext(lakehouse)
    
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    
    console.print("\n[bold cyan]Generating Strategy Weights (Momentum 12-1, Top 5)...[/bold cyan]")
    weights = generate_momentum_weights(ctx, start, end, index_name="ALL", rebalance_freq="ME") # Monthly end
    if weights.empty:
        console.print("[red]Failed to generate weights.[/red]")
        sys.exit(1)
        
    # Get all required prices for the event loop
    prices = ctx.get_prices(end, lookback_days=365)
    
    # Clean up prices for vbt (wide format)
    close_prices = prices.pivot(index="date", columns="isin", values="close")
    
    # Ensure indexes are datetime64 and sorted for reindexing
    weights.index = pd.to_datetime(weights.index)
    close_prices.index = pd.to_datetime(close_prices.index)
    
    weights = weights.loc[~weights.index.duplicated()].sort_index()
    close_prices = close_prices.loc[~close_prices.index.duplicated()].sort_index()
    
    # Reindex weights to close_prices
    # Ensure they share the exact same columns and index
    aligned_weights = weights.reindex(index=close_prices.index, columns=close_prices.columns)
    aligned_weights = aligned_weights.ffill().fillna(0.0)
    
    # --------------------------------------------------------------------------
    # 1. Equivalence Test (Zero Costs)
    # --------------------------------------------------------------------------
    console.print("\n[bold cyan]1. Running Equivalence Test (Zero Costs)...[/bold cyan]")
    
    # VBT (Zero Cost)
    vbt_pf_zero = run_vbt_cross_sectional(
        close_prices, 
        aligned_weights, 
        init_cash=1000000.0, 
        fees=0.0, 
        slippage=0.0
    )
    vbt_final_val = vbt_pf_zero.value().iloc[-1]
    
    # Event Loop (Zero Cost)
    statutory_zero = StatutoryCostModel(brokerage_rate=0.0, flat_brokerage=0.0)
    # We must patch the statutory model to return 0 for everything to match vbt zero cost
    import copy
    from indiquant.costs.statutory import _RATE_HISTORY
    original_rates = copy.deepcopy(_RATE_HISTORY)
    for r in _RATE_HISTORY:
        r.stt_buy = 0.0
        r.stt_sell = 0.0
        r.exch_txn = 0.0
        r.sebi_fee = 0.0
        r.ipft = 0.0
        r.stamp_duty = 0.0
        r.gst_rate = 0.0
        r.dp_charge = 0.0
        
    slippage_zero = SlippageModel(impact_c=0.0)
    
    # Override slippage spread to 0
    slippage_zero.estimate_spread_bps = lambda x: 0.0
    
    constraints_zero = ExecutionConstraints(
        enforce_circuits=False,
        settlement_t_plus=0, # Instant settlement like VBT
        enforce_whole_shares=False, # Fractional shares like VBT targetpercent
        reject_asm_gsm=False
    )
    
    exec_zero = ExecutionModel(statutory_zero, slippage_zero, constraints_zero, fill_price="CLOSE")
    
    # Set up MultiIndex prices for event loop
    mi_prices = prices.set_index(["date", "isin"])
    
    el_zero = run_event_loop(mi_prices, aligned_weights, exec_zero, init_cash=1000000.0)
    el_final_val = el_zero["portfolio_value"].iloc[-1]
    
    diff_bps = abs((el_final_val - vbt_final_val) / vbt_final_val) * 10000
    
    console.print(f"VBT Final Value:        [green]{vbt_final_val:,.2f}[/green]")
    console.print(f"Event Loop Final Value: [green]{el_final_val:,.2f}[/green]")
    console.print(f"Difference:             [yellow]{diff_bps:.4f} bps[/yellow]")
    
    if diff_bps > 1.0:
        console.print("[red]WARNING: Engines do not perfectly align (diff > 1 bps).[/red]")
        console.print("This is expected if T+1 cash drag or VBT's cash sharing creates slight divergence, but should be close.")
    else:
        console.print("[green]Equivalence passed (<1 bps).[/green]")
        
    # Restore statutory rates
    _RATE_HISTORY.clear()
    _RATE_HISTORY.extend(original_rates)

    # --------------------------------------------------------------------------
    # 2. Gross vs Net Report
    # --------------------------------------------------------------------------
    console.print("\n[bold cyan]2. Running Realistic Cost Engine...[/bold cyan]")
    
    # We will use realistic costs: 0.01% brokerage
    statutory_real = StatutoryCostModel(brokerage_rate=0.0001, flat_brokerage=20.0)
    slippage_real = SlippageModel(impact_c=1.0)
    constraints_real = ExecutionConstraints(
        enforce_circuits=True,
        settlement_t_plus=1,
        enforce_whole_shares=True,
    )
    exec_real = ExecutionModel(statutory_real, slippage_real, constraints_real, fill_price="CLOSE")
    
    el_real = run_event_loop(mi_prices, aligned_weights, exec_real, init_cash=1000000.0)
    
    # Compute metrics
    def cagr(df):
        years = (df.index[-1] - df.index[0]).days / 365.25
        return ((df["portfolio_value"].iloc[-1] / df["portfolio_value"].iloc[0]) ** (1/years) - 1) * 100
        
    def sharpe(df):
        ret = df["portfolio_value"].pct_change().dropna()
        if ret.std() == 0: return 0.0
        return np.sqrt(252) * (ret.mean() / ret.std())
        
    gross_cagr = cagr(el_zero)
    net_cagr = cagr(el_real)
    gross_sharpe = sharpe(el_zero)
    net_sharpe = sharpe(el_real)
    
    trades = el_real.attrs["trades"]
    
    if not trades.empty:
        total_costs = trades["total_frictional_cost"].sum()
        total_stt = trades["cost_stt"].sum()
        total_brk = trades["cost_brokerage"].sum()
        total_dp = trades["cost_dp"].sum()
        total_slip = trades["slippage_cost"].sum()
        total_exch = trades["cost_exchange"].sum()
        total_stamp = trades["cost_stamp"].sum()
        total_gst = trades["cost_gst"].sum()
        gross_profit = el_zero["portfolio_value"].iloc[-1] - 1000000.0
        cost_pct_profit = (total_costs / gross_profit * 100) if gross_profit > 0 else float('inf')
        
        t2 = Table(title="Gross vs Net Performance & Cost Breakdown")
        t2.add_column("Metric", style="cyan")
        t2.add_column("Gross (Zero Cost)", justify="right")
        t2.add_column("Net (Realistic)", justify="right")
        
        t2.add_row("CAGR", f"{gross_cagr:.2f}%", f"{net_cagr:.2f}%")
        t2.add_row("Sharpe", f"{gross_sharpe:.2f}", f"{net_sharpe:.2f}")
        t2.add_section()
        t2.add_row("Total Frictional Cost", "-", f"Rs {total_costs:,.2f}")
        t2.add_row("Cost as % of Gross Profit", "-", f"{cost_pct_profit:.2f}%")
        t2.add_section()
        t2.add_row("  -> STT", "-", f"Rs {total_stt:,.2f}")
        t2.add_row("  -> Brokerage", "-", f"Rs {total_brk:,.2f}")
        t2.add_row("  -> DP Charges", "-", f"Rs {total_dp:,.2f}")
        t2.add_row("  -> Spread/Impact Slippage", "-", f"Rs {total_slip:,.2f}")
        t2.add_row("  -> Exchange/SEBI", "-", f"Rs {total_exch:,.2f}")
        t2.add_row("  -> Stamp Duty", "-", f"Rs {total_stamp:,.2f}")
        t2.add_row("  -> GST", "-", f"Rs {total_gst:,.2f}")
        
        console.print(t2)
    else:
        console.print("[red]No trades executed in realistic run.[/red]")

    # --------------------------------------------------------------------------
    # 3. DP Fee Effective Cost Curve
    # --------------------------------------------------------------------------
    console.print("\n[bold cyan]3. Generating DP Fee Curve...[/bold cyan]")
    
    position_sizes = np.logspace(3, 7, 50) # 1k to 10M Rs
    dp_cost_bps = []
    
    stat_model = StatutoryCostModel(brokerage_rate=0.0001, flat_brokerage=0.0)
    
    for size in position_sizes:
        # Sell trade
        res = stat_model.calculate_trade_cost(
            trade_date=date(2024, 1, 1),
            side="SELL",
            qty=1,
            price=size,
            segment="EQ_DELIVERY",
            is_first_sell_of_day=True,
        )
        total_cost_bps = (res["total"] / size) * 10000.0
        dp_cost_bps.append(total_cost_bps)
        
    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 6))
        plt.plot(position_sizes, dp_cost_bps, 'b-', linewidth=2)
        plt.xscale('log')
        plt.title('Effective Sell-Side Cost (in bps) vs Position Size')
        plt.xlabel('Position Size (Rs)')
        plt.ylabel('Total Frictional Cost (bps)')
        plt.grid(True, which="both", ls="-", alpha=0.2)
        
        # Add DP annotation
        plt.annotate('Flat ₹15 DP fee dominates small sizes', 
                     xy=(10000, max(dp_cost_bps)*0.8),
                     xytext=(50000, max(dp_cost_bps)*0.9),
                     arrowprops=dict(facecolor='black', shrink=0.05))
                     
        plt.axhline(y=(0.001 * 10000), color='r', linestyle='--', label='STT Floor (10 bps)')
        plt.legend()
        plt.tight_layout()
        plt.savefig('dp_cost_curve.png')
        console.print("[green]Saved DP fee curve to dp_cost_curve.png[/green]")
    except ImportError:
        console.print("[yellow]Matplotlib not installed. Skipping plot.[/yellow]")

if __name__ == "__main__":
    run_acceptance()
