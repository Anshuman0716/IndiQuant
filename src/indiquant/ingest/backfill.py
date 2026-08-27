"""Backfill orchestrator with three-state date classification.

Every date is classified as one of:
    is_holiday         — skip with info log, no failure counter
    is_trading_day     — proceed with fetch → validate → land → promote
    is_confirmed_gap   — trading day where fetch or validate failed

Behavior on is_confirmed_gap is branched by mode:
    backfill     — hard-fail immediately (incomplete lakehouse is unacceptable)
    incremental  — warn-and-continue, write row to data_quality table
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from indiquant.ingest.calendar import TradingCalendar

if TYPE_CHECKING:
    from indiquant.ingest.base import Source
    from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


class BackfillMode(StrEnum):
    """Controls gap-handling behavior."""

    BACKFILL = "backfill"  # One-shot historical load — hard-fail on gaps
    INCREMENTAL = "incremental"  # Daily refresh — warn-and-continue


class ConfirmedGapError(Exception):
    """Raised in backfill mode when a trading day has no data.

    A silently incomplete lakehouse is worse than a stopped backfill.
    """

    def __init__(self, source: str, target_date: date, reason: str) -> None:
        self.source = source
        self.target_date = target_date
        self.reason = reason
        super().__init__(f"Confirmed gap for {source} on {target_date}: {reason}")


@dataclass
class SourceReport:
    """Per-source summary of a backfill run."""

    source_name: str
    dates_processed: int = 0
    dates_skipped_holiday: int = 0
    dates_skipped_existing: int = 0
    dates_succeeded: int = 0
    dates_failed: int = 0
    failed_dates: list[date] = field(default_factory=list)


@dataclass
class BackfillReport:
    """Aggregated result of a backfill run across all sources."""

    start: date
    end: date
    mode: BackfillMode
    source_reports: dict[str, SourceReport] = field(default_factory=dict)
    aborted: bool = False
    abort_reason: str | None = None


def _write_gap_to_quality(
    lakehouse: Lakehouse,
    source_name: str,
    target_date: date,
    reason: str,
) -> None:
    """Write a confirmed-gap record to the data_quality meta table.

    In incremental mode, this is the ONLY acceptable way to record a gap —
    not just stdout. P9 freshness alerting watches this table.
    """
    import json
    import uuid

    record = {
        "source": source_name,
        "run_id": str(uuid.uuid4()),
        "run_date": datetime.now(UTC).isoformat(),
        "target_date": target_date.isoformat(),
        "row_count": 0,
        "null_counts_json": "{}",
        "validation_failures": 1,
        "date_gaps_json": json.dumps([{"date": target_date.isoformat(), "reason": reason}]),
        "ingested_at": datetime.now(UTC).isoformat(),
    }
    lakehouse.write_quality_log(record)


def run_backfill(
    start: date,
    end: date,
    sources: list[Source],
    mode: BackfillMode,
    lakehouse: Lakehouse,
    calendar: TradingCalendar | None = None,
) -> BackfillReport:
    """Execute backfill for all sources across the date range.

    Sources are run in the order provided — the caller is responsible for
    dependency ordering (e.g. corporate_actions before bhavcopy).

    Args:
        start: First date to backfill (inclusive).
        end: Last date to backfill (inclusive).
        sources: List of Source instances in dependency order.
        mode: Controls gap-handling behavior.
        lakehouse: Lakehouse instance.
        calendar: Trading calendar for holiday classification.
            If None, a new one is loaded from the default path.

    Returns:
        BackfillReport with per-source statistics.

    Raises:
        ConfirmedGapError: In backfill mode, when a trading day has no data.
    """
    if calendar is None:
        calendar = TradingCalendar()

    # In bootstrap mode (calendar not loaded), we can only classify weekends.
    # Weekday holidays will be treated as trading days and may fail —
    # that's expected and handled below.
    bootstrap_mode = not calendar.is_loaded

    if bootstrap_mode:
        logger.warning(
            "backfill_bootstrap_mode",
            msg=(
                "Holiday calendar not loaded. Running in bootstrap mode: "
                "weekday failures will be logged as potential holidays. "
                "Only source #1 (bhavcopy) should be run in this mode."
            ),
        )

    report = BackfillReport(start=start, end=end, mode=mode)

    for source in sources:
        source_report = SourceReport(source_name=source.name)
        report.source_reports[source.name] = source_report

        logger.info(
            "backfill_source_start",
            source=source.name,
            start=start.isoformat(),
            end=end.isoformat(),
            mode=mode.value,
        )

        # Generate all candidate dates
        import pandas as pd

        all_dates = pd.date_range(start, end)

        for ts in all_dates:
            target_date = ts.date()
            source_report.dates_processed += 1

            # ── State 1: is_holiday ──
            if not bootstrap_mode and calendar.is_holiday(target_date):
                logger.info(
                    "date_is_holiday",
                    source=source.name,
                    date=target_date.isoformat(),
                )
                source_report.dates_skipped_holiday += 1
                continue

            # Skip weekends in bootstrap mode (we know these aren't trading days)
            if bootstrap_mode and target_date.weekday() >= 5:
                source_report.dates_skipped_holiday += 1
                continue

            # ── State 2: is_trading_day — attempt fetch + validate ──
            try:
                validation_report = source.run(target_date)
            except Exception as exc:
                # fetch() or run() raised — this is a confirmed gap
                reason = f"Exception during fetch/run: {exc}"
                _handle_confirmed_gap(
                    source=source,
                    source_report=source_report,
                    target_date=target_date,
                    reason=reason,
                    mode=mode,
                    lakehouse=lakehouse,
                    bootstrap_mode=bootstrap_mode,
                    report=report,
                )
                if report.aborted:
                    return report
                continue

            # validate() returned but may have error-severity issues
            if not validation_report.passed:
                reason = "; ".join(
                    f"[{i.check_name}] {i.message}"
                    for i in validation_report.issues
                    if i.severity == "error"
                )
                _handle_confirmed_gap(
                    source=source,
                    source_report=source_report,
                    target_date=target_date,
                    reason=reason,
                    mode=mode,
                    lakehouse=lakehouse,
                    bootstrap_mode=bootstrap_mode,
                    report=report,
                )
                if report.aborted:
                    return report
                continue

            source_report.dates_succeeded += 1
            logger.debug(
                "date_ingested",
                source=source.name,
                date=target_date.isoformat(),
                rows=validation_report.total_rows,
            )

        logger.info(
            "backfill_source_complete",
            source=source.name,
            processed=source_report.dates_processed,
            succeeded=source_report.dates_succeeded,
            holidays=source_report.dates_skipped_holiday,
            existing=source_report.dates_skipped_existing,
            failed=source_report.dates_failed,
        )

    return report


def _handle_confirmed_gap(
    source: Source,
    source_report: SourceReport,
    target_date: date,
    reason: str,
    mode: BackfillMode,
    lakehouse: Lakehouse,
    bootstrap_mode: bool,
    report: BackfillReport,
) -> None:
    """Handle a confirmed gap based on mode.

    backfill mode  → hard-fail (unless bootstrap mode)
    incremental    → warn-and-continue, write to data_quality
    bootstrap      → warn-and-continue (first bhavcopy run only)
    """
    source_report.dates_failed += 1
    source_report.failed_dates.append(target_date)

    if bootstrap_mode:
        # Bootstrap mode: we don't know if this is a holiday or a real gap.
        # Log as warning and continue — the derived calendar will sort it out.
        logger.warning(
            "bootstrap_potential_holiday",
            source=source.name,
            date=target_date.isoformat(),
            reason=reason,
            msg="May be a holiday. Will be classified after calendar derivation.",
        )
        return

    if mode == BackfillMode.INCREMENTAL:
        # Write gap to data_quality table (not just stdout) so P9 alerting sees it
        logger.warning(
            "confirmed_gap_incremental",
            source=source.name,
            date=target_date.isoformat(),
            reason=reason,
        )
        _write_gap_to_quality(lakehouse, source.name, target_date, reason)
        return

    # mode == BackfillMode.BACKFILL → hard-fail
    logger.error(
        "confirmed_gap_backfill",
        source=source.name,
        date=target_date.isoformat(),
        reason=reason,
        msg="Hard-failing backfill. Fix the gap and re-run.",
    )
    report.aborted = True
    report.abort_reason = f"Confirmed gap for {source.name} on {target_date}: {reason}"
