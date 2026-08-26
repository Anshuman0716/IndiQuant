import typer

from indiquant.ingest.cli import ingest_app

app = typer.Typer(
    name="iq",
    help="IndiQuant — Systematic Indian Equity Research & Backtesting CLI.",
    no_args_is_help=True,
)

app.add_typer(ingest_app, name="ingest")


def cli() -> None:
    app()


if __name__ == "__main__":
    cli()
