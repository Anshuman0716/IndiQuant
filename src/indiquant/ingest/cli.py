import typer
from datetime import date
from typing import Annotated

ingest_app = typer.Typer(
    name="ingest",
    help="Ingest and sync market data into the lakehouse.",
    no_args_is_help=True,
)

@ingest_app.command("run", help="Run ingestion pipeline for a given source and date range.")
def run(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help="Source identifier to ingest.",
        ),
    ],
    from_date: Annotated[
        date,
        typer.Option(
            "--from",
            "-f",
            help="Start date in YYYY-MM-DD format.",
            formats=["%Y-%m-%d"],
        ),
    ],
    to_date: Annotated[
        date,
        typer.Option(
            "--to",
            "-t",
            help="End date in YYYY-MM-DD format.",
            formats=["%Y-%m-%d"],
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing partitioned parquet files.",
        ),
    ] = False,
) -> None:
    """Execute data ingestion from source within the specified date range."""
    typer.echo(f"Starting ingestion from '{source}' from {from_date} to {to_date} (force={force})")


@ingest_app.command("status", help="Show status and latest knowledge dates in lakehouse.")
def status() -> None:
    """Check ingestion status."""
    typer.echo("Lakehouse partition status: OK")


@ingest_app.command("gaps", help="Report missing market days for a source.")
def gaps(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help="Source identifier to check for gaps.",
        ),
    ],
) -> None:
    typer.echo(f"Checking gaps for {source}")
