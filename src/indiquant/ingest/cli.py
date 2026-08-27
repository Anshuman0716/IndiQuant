"""Ingestion CLI subcommands for the iq CLI."""

from datetime import date, datetime
from typing import Annotated

import typer

from indiquant.ingest.backfill import BackfillMode

ingest_app = typer.Typer(
    name="ingest",
    help="Ingest and sync market data into the lakehouse.",
    no_args_is_help=True,
)


@ingest_app.command("backfill")
def backfill(
    from_date: Annotated[
        datetime,
        typer.Option(
            "--from",
            "-f",
            help="Start date in YYYY-MM-DD format.",
            formats=["%Y-%m-%d"],
        ),
    ],
    to_date: Annotated[
        datetime,
        typer.Option(
            "--to",
            "-t",
            help="End date in YYYY-MM-DD format.",
            formats=["%Y-%m-%d"],
        ),
    ],
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            "-s",
            help="Specific source to backfill. Omit for all sources in dependency order.",
        ),
    ] = None,
    mode: Annotated[
        BackfillMode,
        typer.Option(
            "--mode",
            "-m",
            help="backfill (hard-fail on gaps) or incremental (warn-and-continue).",
        ),
    ] = BackfillMode.BACKFILL,
) -> None:
    """Run backfill for data sources across a date range."""
    from indiquant.config.settings import IndiQuantSettings
    from indiquant.ingest.backfill import run_backfill
    from indiquant.ingest.sources.bulk_block_deals import BulkBlockDealsSource
    from indiquant.ingest.sources.corporate_actions import CorporateActionsSource
    from indiquant.ingest.sources.fii_dii import FiiDiiSource
    from indiquant.ingest.sources.fundamentals import FundamentalsSource
    from indiquant.ingest.sources.index_membership import IndexMembershipSource
    from indiquant.ingest.sources.nse_bhavcopy import EquityBhavcopySource
    from indiquant.ingest.sources.nse_fo_bhavcopy import FoBhavcopySource
    from indiquant.ingest.sources.nse_participant_oi import ParticipantOiSource
    from indiquant.ingest.sources.shareholding import ShareholdingSource
    from indiquant.logging import setup_logging
    from indiquant.store.lakehouse import Lakehouse

    setup_logging()
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)

    # Source registry in dependency order
    all_sources = {
        "nse_corporate_actions": CorporateActionsSource(lakehouse),
        "nse_index_membership": IndexMembershipSource(lakehouse),
        "nse_equity_daily": EquityBhavcopySource(lakehouse),
        "nse_fo_daily": FoBhavcopySource(lakehouse),
        "nse_participant_oi": ParticipantOiSource(lakehouse),
        "nse_fii_dii": FiiDiiSource(lakehouse),
        "nse_bulk_block_deals": BulkBlockDealsSource(lakehouse),
        "nse_shareholding": ShareholdingSource(lakehouse),
        "nse_fundamentals": FundamentalsSource(lakehouse),
    }

    if source:
        if source not in all_sources:
            typer.echo(f"Unknown source: {source}. Available: {list(all_sources.keys())}")
            raise typer.Exit(1)
        sources_to_run = [all_sources[source]]
    else:
        sources_to_run = list(all_sources.values())

    typer.echo(
        f"Backfill: {from_date.date()} → {to_date.date()}, "
        f"sources={[s.name for s in sources_to_run]}, mode={mode.value}"
    )

    report = run_backfill(
        start=from_date.date(),
        end=to_date.date(),
        sources=sources_to_run,
        mode=mode,
        lakehouse=lakehouse,
    )

    # Print summary
    typer.echo("\n" + "=" * 60)
    typer.echo("BACKFILL REPORT")
    typer.echo("=" * 60)

    for name, sr in report.source_reports.items():
        typer.echo(f"\n  {name}:")
        typer.echo(f"    Processed:  {sr.dates_processed}")
        typer.echo(f"    Succeeded:  {sr.dates_succeeded}")
        typer.echo(f"    Holidays:   {sr.dates_skipped_holiday}")
        typer.echo(f"    Failed:     {sr.dates_failed}")
        if sr.failed_dates:
            typer.echo(f"    Failed on:  {[d.isoformat() for d in sr.failed_dates[:10]]}")

    if report.aborted:
        typer.echo(f"\n  ABORTED: {report.abort_reason}")
        raise typer.Exit(1)


@ingest_app.command("status")
def status() -> None:
    """Show ingestion status: row counts, date coverage, and gaps."""
    from indiquant.config.settings import IndiQuantSettings
    from indiquant.store.lakehouse import Lakehouse

    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)

    # Check each silver table
    tables = ["equity_daily", "corporate_actions", "index_membership"]

    typer.echo("=" * 60)
    typer.echo("LAKEHOUSE STATUS")
    typer.echo("=" * 60)

    for table in tables:
        try:
            df = lakehouse.read_table(table)
            typer.echo(f"\n  {table}:")
            typer.echo(f"    Rows:       {len(df)}")
            if "date" in df.columns:
                typer.echo(f"    Min date:   {df['date'].min()}")
                typer.echo(f"    Max date:   {df['date'].max()}")
            if "isin" in df.columns:
                typer.echo(f"    ISINs:      {df['isin'].nunique()}")
        except Exception:
            typer.echo(f"\n  {table}: No data")

    # Show data quality summary
    try:
        quality = lakehouse.read_quality_log()
        if not quality.empty:
            typer.echo(f"\n  Data quality log: {len(quality)} entries")
            failed = quality[quality["validation_failures"] > 0]
            if not failed.empty:
                typer.echo(f"    With failures: {len(failed)}")
    except Exception:
        pass


@ingest_app.command("derive-calendar")
def derive_calendar(
    from_date: Annotated[
        datetime,
        typer.Option(
            "--from",
            "-f",
            help="Start date.",
            formats=["%Y-%m-%d"],
        ),
    ],
    to_date: Annotated[
        datetime,
        typer.Option(
            "--to",
            "-t",
            help="End date.",
            formats=["%Y-%m-%d"],
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Output path for derived calendar CSV (for human review).",
        ),
    ] = "derived_nse_holidays.csv",
) -> None:
    """Derive NSE holiday calendar from bhavcopy coverage.

    Run this AFTER the initial bhavcopy backfill. Review the output CSV,
    then freeze it as ingest/reference/nse_holidays.parquet.
    """
    from indiquant.config.settings import IndiQuantSettings
    from indiquant.ingest.calendar import derive_holiday_calendar
    from indiquant.store.lakehouse import Lakehouse

    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)

    # Get all dates that have bhavcopy data
    try:
        df = lakehouse.read_table("equity_daily")
        if "date" in df.columns:
            bhavcopy_dates = {date.fromisoformat(d) for d in df["date"].unique()}
        else:
            bhavcopy_dates = set()
    except Exception as e:
        typer.echo("No bhavcopy data found. Run backfill first.")
        raise typer.Exit(1) from e

    calendar_df = derive_holiday_calendar(bhavcopy_dates, from_date.date(), to_date.date())

    # Write CSV for human review
    calendar_df.write_csv(output)
    typer.echo(f"Derived {len(calendar_df)} calendar entries → {output}")
    typer.echo("Review this file, then freeze as ingest/reference/nse_holidays.parquet")

    import polars as pl

    holidays = calendar_df.filter(pl.col("is_holiday"))
    specials = calendar_df.filter(pl.col("is_special_session"))
    typer.echo(f"  Holidays:         {len(holidays)}")
    typer.echo(f"  Special sessions: {len(specials)}")
