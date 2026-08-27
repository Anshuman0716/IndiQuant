"""Tests for NSE trading calendar module."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from indiquant.ingest.calendar import TradingCalendar, derive_holiday_calendar


@pytest.fixture
def sample_calendar(tmp_path: Path) -> TradingCalendar:
    """Calendar with Republic Day and a Muhurat Trading session."""
    holidays_path = tmp_path / "holidays.parquet"
    df = pl.DataFrame(
        {
            "date": ["2024-01-26", "2024-11-01"],  # Republic Day, Muhurat Sat
            "is_holiday": [True, False],
            "is_special_session": [False, True],
        }
    )
    df.write_parquet(holidays_path)
    return TradingCalendar(holidays_path)


def test_weekday_holiday_detected(sample_calendar: TradingCalendar) -> None:
    """Republic Day (weekday) is a holiday."""
    assert sample_calendar.is_holiday(date(2024, 1, 26))
    assert not sample_calendar.is_trading_day(date(2024, 1, 26))


def test_normal_weekday_is_trading_day(sample_calendar: TradingCalendar) -> None:
    """A normal Monday is a trading day."""
    assert sample_calendar.is_trading_day(date(2024, 1, 22))
    assert not sample_calendar.is_holiday(date(2024, 1, 22))


def test_weekend_is_holiday(sample_calendar: TradingCalendar) -> None:
    """Normal weekends are holidays."""
    assert sample_calendar.is_holiday(date(2024, 1, 27))  # Saturday
    assert sample_calendar.is_holiday(date(2024, 1, 28))  # Sunday


def test_special_session_is_trading_day(sample_calendar: TradingCalendar) -> None:
    """Muhurat Trading (special session on a Saturday) is a trading day."""
    # Nov 1 2024 is a Friday in reality, but we set it as special_session for test
    assert sample_calendar.is_special_session(date(2024, 11, 1))
    assert not sample_calendar.is_holiday(date(2024, 11, 1))


def test_trading_days_range(sample_calendar: TradingCalendar) -> None:
    """trading_days() returns correct list excluding holidays and weekends."""
    days = sample_calendar.trading_days(date(2024, 1, 22), date(2024, 1, 29))
    # Mon=22, Tue=23, Wed=24, Thu=25, Fri=26(holiday), Sat=27, Sun=28, Mon=29
    assert date(2024, 1, 22) in days
    assert date(2024, 1, 26) not in days  # Holiday
    assert date(2024, 1, 27) not in days  # Saturday
    assert date(2024, 1, 29) in days


def test_calendar_not_loaded(tmp_path: Path) -> None:
    """Calendar from nonexistent path reports not loaded."""
    cal = TradingCalendar(tmp_path / "nonexistent.parquet")
    assert not cal.is_loaded
    # Without a calendar, weekdays are treated as potential trading days
    assert cal.is_trading_day(date(2024, 1, 26))  # Republic Day, but unknown


# ── derive_holiday_calendar tests ──


def test_derive_holiday_weekday_without_data() -> None:
    """Weekday without bhavcopy data → holiday candidate."""
    bhavcopy_dates = {
        date(2024, 1, 22),  # Mon
        date(2024, 1, 23),  # Tue
        date(2024, 1, 24),  # Wed
        date(2024, 1, 25),  # Thu
        # Jan 26 (Fri) missing — holiday candidate
        date(2024, 1, 29),  # Mon
    }
    result = derive_holiday_calendar(bhavcopy_dates, date(2024, 1, 22), date(2024, 1, 29))
    holidays = result.filter(pl.col("is_holiday"))
    assert len(holidays) == 1
    assert holidays["date"][0] == "2024-01-26"


def test_derive_special_session() -> None:
    """Saturday with bhavcopy data → special session (Muhurat Trading)."""
    bhavcopy_dates = {
        date(2024, 11, 1),  # Fri
        date(2024, 11, 2),  # Sat — has data!
    }
    result = derive_holiday_calendar(bhavcopy_dates, date(2024, 11, 1), date(2024, 11, 3))
    specials = result.filter(pl.col("is_special_session"))
    assert len(specials) == 1
    assert specials["date"][0] == "2024-11-02"
