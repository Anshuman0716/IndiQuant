"""Tests for backfill orchestrator: three-state date classification + mode branching."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from indiquant.config.settings import IndiQuantSettings
from indiquant.ingest.backfill import BackfillMode, run_backfill
from indiquant.ingest.calendar import TradingCalendar
from indiquant.ingest.models import ValidationReport
from indiquant.store.lakehouse import Lakehouse


class _FakeSource:
    """Minimal Source stand-in for orchestrator tests."""

    def __init__(self, name: str, fail_dates: set[date] | None = None) -> None:
        self.name = name
        self._fail_dates = fail_dates or set()
        self.dates_called: list[date] = []

    def run(self, target_date: date, *, force: bool = False) -> ValidationReport:
        self.dates_called.append(target_date)
        if target_date in self._fail_dates:
            raise ConnectionError(f"Simulated fetch failure on {target_date}")
        return ValidationReport(
            source=self.name,
            date=target_date,
            total_rows=1800,
            issues=[],
        )


@pytest.fixture
def tmp_lakehouse(tmp_path: Path) -> Lakehouse:
    settings = IndiQuantSettings(data_dir=tmp_path)
    return Lakehouse(settings)


@pytest.fixture
def holiday_calendar(tmp_path: Path) -> TradingCalendar:
    """Calendar with 2024-01-26 (Republic Day) as a holiday."""
    holidays_path = tmp_path / "holidays.parquet"
    df = pl.DataFrame(
        {
            "date": ["2024-01-26"],
            "is_holiday": [True],
            "is_special_session": [False],
        }
    )
    df.write_parquet(holidays_path)
    return TradingCalendar(holidays_path)


def test_holiday_is_skipped(tmp_lakehouse: Lakehouse, holiday_calendar: TradingCalendar) -> None:
    """Holidays are skipped with no failure counter increment."""
    source = _FakeSource("test")

    report = run_backfill(
        start=date(2024, 1, 25),  # Thu
        end=date(2024, 1, 29),  # Mon
        sources=[source],  # type: ignore[list-item]
        mode=BackfillMode.BACKFILL,
        lakehouse=tmp_lakehouse,
        calendar=holiday_calendar,
    )

    sr = report.source_reports["test"]
    # Jan 26 (Fri, holiday) + Jan 27-28 (Sat-Sun) should be skipped
    # Only Jan 25 (Thu) and Jan 29 (Mon) should be processed
    assert date(2024, 1, 26) not in source.dates_called
    assert sr.dates_skipped_holiday > 0
    assert sr.dates_failed == 0
    assert not report.aborted


def test_backfill_mode_hardfails_on_gap(
    tmp_lakehouse: Lakehouse, holiday_calendar: TradingCalendar
) -> None:
    """In backfill mode, a confirmed gap aborts immediately."""
    source = _FakeSource("test", fail_dates={date(2024, 1, 25)})

    report = run_backfill(
        start=date(2024, 1, 25),
        end=date(2024, 1, 29),
        sources=[source],  # type: ignore[list-item]
        mode=BackfillMode.BACKFILL,
        lakehouse=tmp_lakehouse,
        calendar=holiday_calendar,
    )

    assert report.aborted
    assert "test" in report.abort_reason
    assert "2024-01-25" in report.abort_reason


def test_incremental_mode_continues_on_gap(
    tmp_lakehouse: Lakehouse, holiday_calendar: TradingCalendar
) -> None:
    """In incremental mode, a confirmed gap writes to data_quality and continues."""
    source = _FakeSource("test", fail_dates={date(2024, 1, 25)})

    report = run_backfill(
        start=date(2024, 1, 25),
        end=date(2024, 1, 29),
        sources=[source],  # type: ignore[list-item]
        mode=BackfillMode.INCREMENTAL,
        lakehouse=tmp_lakehouse,
        calendar=holiday_calendar,
    )

    sr = report.source_reports["test"]
    assert not report.aborted
    assert sr.dates_failed == 1
    assert date(2024, 1, 25) in sr.failed_dates
    # Jan 29 should still have been processed
    assert date(2024, 1, 29) in source.dates_called


def test_weekends_skipped(tmp_lakehouse: Lakehouse, holiday_calendar: TradingCalendar) -> None:
    """Weekends are always skipped (unless special session)."""
    source = _FakeSource("test")

    report = run_backfill(
        start=date(2024, 1, 22),  # Mon
        end=date(2024, 1, 28),  # Sun
        sources=[source],  # type: ignore[list-item]
        mode=BackfillMode.BACKFILL,
        lakehouse=tmp_lakehouse,
        calendar=holiday_calendar,
    )

    sr = report.source_reports["test"]  # noqa: F841
    # Mon-Fri = 5 days, minus holiday (Jan 26) = 4 trading days
    # But Jan 27 (Sat) and Jan 28 (Sun) are weekends
    assert date(2024, 1, 27) not in source.dates_called
    assert date(2024, 1, 28) not in source.dates_called


def test_bootstrap_mode_without_calendar(tmp_lakehouse: Lakehouse) -> None:
    """Without a calendar, bootstrap mode treats weekday failures as potential holidays."""
    source = _FakeSource("test", fail_dates={date(2024, 1, 26)})  # Republic Day

    # No calendar provided → bootstrap mode
    report = run_backfill(
        start=date(2024, 1, 25),
        end=date(2024, 1, 29),
        sources=[source],  # type: ignore[list-item]
        mode=BackfillMode.BACKFILL,
        lakehouse=tmp_lakehouse,
        calendar=TradingCalendar(Path("/nonexistent/path")),
    )

    # Bootstrap mode should NOT hard-fail even in backfill mode
    assert not report.aborted
    sr = report.source_reports["test"]
    assert sr.dates_failed == 1  # The holiday was a "failed" date
