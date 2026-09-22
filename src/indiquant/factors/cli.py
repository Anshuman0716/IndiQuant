"""CLI for factor evaluation and diagnostics."""

from datetime import date
from typing import Annotated

import typer
import structlog
from rich.console import Console
from rich.table import Table

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext, FactorRegistry
from indiquant.factors.diagnostics import compute_decile_report

# Ensure modules are imported so factors are registered
import indiquant.factors.quality
import indiquant.factors.value
import indiquant.factors.growth
import indiquant.factors.volatility
import indiquant.factors.momentum
import indiquant.factors.microstructure

logger = structlog.get_logger(__name__)
factors_app = typer.Typer(help="Factor library evaluation and reporting")
console = Console()


@factors_app.command("list")
def list_factors() -> None:
    """List all registered factors."""
    table = Table(title="Tapetide Factor Registry")
    table.add_column("Pillar")
    table.add_column("Factor ID")
    table.add_column("Direction")
    table.add_column("Min History")
    
    from indiquant.factors.base import registry as f_registry
    
    # Sort by pillar then ID
    sorted_factors = sorted(
        f_registry._factors.items(), 
        key=lambda x: (x[1].pillar, x[0])
    )
    
    for factor_id, meta in sorted_factors:
        dir_str = "Higher is Better" if meta.direction == 1 else ("Lower is Better" if meta.direction == -1 else "Neutral")
        table.add_row(
            meta.pillar,
            factor_id,
            dir_str,
            f"{meta.min_history_days} days"
        )
        
    console.print(table)


from datetime import datetime

@factors_app.command("decile-report")
def decile_report(
    factor: Annotated[str, typer.Option("--factor", "-f", help="Factor ID to evaluate")],
    index: Annotated[str, typer.Option("--index", "-i", help="Universe index (e.g., 'NIFTY 50')")],
    start: Annotated[datetime, typer.Option("--start", "-s", help="Start date (YYYY-MM-DD)", formats=["%Y-%m-%d"])],
    end: Annotated[datetime, typer.Option("--end", "-e", help="End date (YYYY-MM-DD)", formats=["%Y-%m-%d"], default_factory=datetime.now)],
    eval_freq: Annotated[int, typer.Option("--eval-freq", help="Days between evaluations")] = 21,
) -> None:
    """Compute and display a historical decile spread report for a factor."""
    # Note: FactorRegistry is instantiated as `registry` but the class methods are not static. 
    # Let's import the `registry` instance directly instead of using the class.
    from indiquant.factors.base import registry as f_registry
    
    if factor not in f_registry._factors:
        console.print(f"[red]Error: Factor '{factor}' not found. Use 'iq factors list' to see available factors.[/red]")
        raise typer.Exit(1)
        
    start_date = start.date()
    end_date = end.date()
        
    console.print(f"[bold blue]Evaluating {factor} on {index} from {start_date} to {end_date}...[/bold blue]")
    
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    ctx = FactorContext(lakehouse)
    
    try:
        summary = compute_decile_report(
            ctx=ctx,
            factor_id=factor,
            index_name=index,
            start_date=start_date,
            end_date=end_date,
            eval_freq_days=eval_freq,
        )
    except Exception as e:
        console.print(f"[bold red]Evaluation failed: {e}[/bold red]")
        raise typer.Exit(1)
        
    if summary.empty:
        console.print("[yellow]No data available for the specified parameters.[/yellow]")
        raise typer.Exit(0)
        
    # Print Source Warning for Smoke Test
    meta = f_registry._factors[factor]
    if "fundamentals" in meta.required_tables:
        console.print("\n[bold yellow]DATA SOURCE: Using fundamentals_smoke (yfinance) for demonstration.[/bold yellow]")
        
    # Render table
    table = Table(title=f"Decile Report: {factor} ({index})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Avg Universe Size", f"{summary['universe_size']:.1f} stocks")
    table.add_row("Information Coefficient (IC)", f"{summary['ic']:.4f}")
    table.add_row("Monotonicity Score", f"{summary['Monotonicity']:.4f}")
    table.add_row("Spread (D1 - D10)", f"{summary['Spread (D1-D10)']:.2f}%")
    table.add_section()
    
    for d in range(1, 11):
        # Format explicitly: Decile 1 is Best if direction=1, Worst if direction=-1
        label = f"Decile {d}"
        if d == 1:
            label += " (Best Values)"
        elif d == 10:
            label += " (Worst Values)"
            
        table.add_row(label, f"{summary[f'D{d}']:.2f}%")
        
    console.print(table)
