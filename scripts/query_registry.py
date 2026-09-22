"""Script to simulate strategy executions and test the trial registry."""

from datetime import date
from indiquant.validation.registry import record_run

@record_run(strategy_name="momentum_12_1")
def run_momentum_backtest(start_date, end_date, index_name="NIFTY 50", lookback=12):
    # Simulate some backtest metrics
    return {
        "gross_sharpe": 1.25,
        "net_sharpe": 0.85,
        "net_cagr": 14.5,
        "max_dd": -22.3,
        "turnover": 4.2,
        "n_trades": 120,
        "tags": "test_run, momentum",
        "notes": "Testing the anti-overfitting registry."
    }

@record_run(strategy_name="tapetide_composite")
def run_composite_backtest(start_date, end_date, index_name="ALL", top_n=10):
    return {
        "gross_sharpe": 1.40,
        "net_sharpe": 0.98,
        "net_cagr": 18.2,
        "max_dd": -15.1,
        "turnover": 3.8,
        "n_trades": 150,
        "tags": "composite",
        "notes": "Full universe composite run."
    }

if __name__ == "__main__":
    import duckdb
    from rich.console import Console
    from rich.table import Table
    console = Console()
    
    console.print("[cyan]Executing 3 backtests to populate registry...[/cyan]")
    run_momentum_backtest(date(2020, 1, 1), date(2024, 1, 1), index_name="NIFTY 100")
    run_momentum_backtest(date(2018, 1, 1), date(2024, 1, 1), index_name="ALL")
    run_composite_backtest(date(2015, 1, 1), date(2024, 1, 1), index_name="ALL")
    
    console.print("[cyan]Querying Trial Registry...[/cyan]")
    
    db_path = "data/registry.duckdb"
    with duckdb.connect(db_path) as conn:
        # Get counts
        counts = conn.execute("SELECT strategy_name, COUNT(*) as trial_count FROM trials GROUP BY strategy_name").df()
        
        t = Table(title="Trial Count Query")
        t.add_column("Strategy Name", style="green")
        t.add_column("Trial Count", style="yellow")
        for _, row in counts.iterrows():
            t.add_row(row["strategy_name"], str(row["trial_count"]))
            
        console.print(t)
        
        # Get latest run details
        console.print("\n[cyan]Latest Trials Snapshot:[/cyan]")
        latest = conn.execute("SELECT timestamp, strategy_name, net_sharpe, net_cagr, params_json FROM trials ORDER BY timestamp DESC LIMIT 5").df()
        
        t2 = Table(title="Recent Trials")
        t2.add_column("Timestamp", style="dim")
        t2.add_column("Strategy")
        t2.add_column("Net Sharpe")
        t2.add_column("Net CAGR (%)")
        t2.add_column("Params Hash (JSON)", overflow="fold")
        for _, row in latest.iterrows():
            t2.add_row(
                str(row["timestamp"])[:19], 
                row["strategy_name"], 
                f"{row['net_sharpe']:.2f}", 
                f"{row['net_cagr']:.2f}",
                row["params_json"][:50] + "..."
            )
        console.print(t2)
