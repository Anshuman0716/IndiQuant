import typer

from indiquant.ingest.cli import ingest_app
from indiquant.factors.cli import factors_app
from indiquant.cli.validation import app as validate_app

app = typer.Typer(
    name="iq",
    help="IndiQuant - Systematic Indian Equity Research & Backtesting CLI.",
    no_args_is_help=True,
)

app.add_typer(ingest_app, name="ingest")
app.add_typer(factors_app, name="factors")
app.add_typer(validate_app, name="validate", help="Anti-overfitting validation harness")

def cli() -> None:
    app()


if __name__ == "__main__":
    cli()
