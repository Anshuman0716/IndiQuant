"""NSE trading calendar: holiday classification and special session detection.

The holiday calendar is bootstrapped from bhavcopy coverage:
1. After the initial bhavcopy backfill (2010–2026), run derive_holiday_calendar()
2. Human reviews the derived list
3. Freeze it as ingest/reference/nse_holidays.parquet — ground truth from then on

This module NEVER re-derives the calendar at runtime. It reads the frozen file.
"""  # noqa: RUF002

from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# Path to the frozen holiday calendar, checked into git as reference data.
_REFERENCE_DIR = Path(__file__).parent / "reference"
_HOLIDAYS_PATH = _REFERENCE_DIR / "nse_holidays.parquet"


class TradingCalendar:
    """NSE trading calendar backed by a frozen Parquet reference file.

    Three-state classification for any date:
    - is_holiday: date is in the frozen calendar
    - is_special_session: weekend with trading (e.g. Muhurat Trading)
    - is_trading_day: everything else (weekday, not a holiday)
    """

    def __init__(self, holidays_path: Path | None = None) -> None:
        """Load the frozen holiday calendar.

        Args:
            holidays_path: Override path, primarily for testing.
                Defaults to ingest/reference/nse_holidays.parquet.
        """
        path = holidays_path or _HOLIDAYS_PATH
        self._holidays: set[date] = set()
        self._special_sessions: set[date] = set()
        self._loaded = False

        if path.exists():
            df = pd.read_parquet(path)
            if "date" in df.columns:
                for _, row in df.iterrows():
                    dt = pd.Timestamp(row["date"]).date()
                    if row.get("is_special_session", False):
                        self._special_sessions.add(dt)
                    else:
                        self._holidays.add(dt)
                self._loaded = True
                logger.info(
                    "calendar_loaded",
                    holidays=len(self._holidays),
                    special_sessions=len(self._special_sessions),
                    path=str(path),
                )
        else:
            logger.warning(
                "calendar_not_found",
                path=str(path),
                msg=(
                    "Holiday calendar not found. Running in bootstrap mode: "
                    "all weekdays treated as potential trading days."
                ),
            )

    @property
    def is_loaded(self) -> bool:
        """True if the frozen calendar was successfully loaded."""
        return self._loaded

    def is_holiday(self, dt: date) -> bool:
        """True if dt is a known NSE holiday (market closed)."""
        # Weekends are always non-trading unless they're special sessions
        if dt.weekday() >= 5:  # Saturday=5, Sunday=6
            return dt not in self._special_sessions
        return dt in self._holidays

    def is_special_session(self, dt: date) -> bool:
        """True if dt is a weekend with trading (e.g. Muhurat Trading)."""
        return dt in self._special_sessions

    def is_trading_day(self, dt: date) -> bool:
        """True if dt should have market data."""
        return not self.is_holiday(dt)

    def trading_days(self, start: date, end: date) -> list[date]:
        """Return all expected trading days in [start, end]."""
        result: list[date] = []
        bdays = pd.bdate_range(start, end)
        for ts in bdays:
            dt = ts.date()
            if not self.is_holiday(dt):
                result.append(dt)
        # Also include special sessions (weekend trading days)
        for dt in sorted(self._special_sessions):
            if start <= dt <= end and dt not in result:
                result.append(dt)
        return sorted(result)


def derive_holiday_calendar(
    bhavcopy_dates: set[date],
    start: date,
    end: date,
) -> pl.DataFrame:
    """Derive NSE holiday calendar from bhavcopy coverage.

    Called ONCE after the initial bhavcopy backfill. The output must be
    manually reviewed by a human, then frozen as nse_holidays.parquet.

    Algorithm:
    - Generate all dates in [start, end]
    - Any weekday WITHOUT a bhavcopy file → holiday candidate
    - Any Saturday/Sunday WITH a bhavcopy file → is_special_session

    Args:
        bhavcopy_dates: Set of dates that have bhavcopy data.
        start: First date of the backfill range.
        end: Last date of the backfill range.

    Returns:
        Polars DataFrame with columns:
            date, day_of_week, day_name, is_holiday, is_special_session, source
    """
    all_dates = pd.date_range(start, end)
    records: list[dict[str, object]] = []

    for ts in all_dates:
        dt = ts.date()
        day_of_week = dt.weekday()
        day_name = dt.strftime("%A")
        has_data = dt in bhavcopy_dates
        is_weekend = day_of_week >= 5

        if is_weekend and has_data:
            # Special session: weekend with trading (Muhurat Trading, etc.)
            records.append(
                {
                    "date": dt.isoformat(),
                    "day_of_week": day_of_week,
                    "day_name": day_name,
                    "is_holiday": False,
                    "is_special_session": True,
                    "source": "derived_from_bhavcopy",
                }
            )
        elif not is_weekend and not has_data:
            # Holiday candidate: weekday without data
            records.append(
                {
                    "date": dt.isoformat(),
                    "day_of_week": day_of_week,
                    "day_name": day_name,
                    "is_holiday": True,
                    "is_special_session": False,
                    "source": "derived_from_bhavcopy",
                }
            )
        # Normal weekdays with data and weekends without data are not recorded

    return pl.DataFrame(records)
