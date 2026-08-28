"""Historical NIFTY index membership (50/100/500).

THIS IS THE SURVIVORSHIP FIX — AGENTS.md Rule #2.

Sources:
  - Current constituents: nsearchives.nseindia.com/content/indices/ind_nifty{N}list.csv
  - Historical additions/removals: nsearchives.nseindia.com/content/indices/IndexInclExcl.csv

Output: (index_name, isin, valid_from, valid_to) with valid_to=NULL for current.
"""

import io
from datetime import date, datetime

import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)

# Index name to CSV URL mapping for current constituents
_INDEX_URLS = {
    "NIFTY 50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY 100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY 500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}

# Master historical inclusion/exclusion file
_INCL_EXCL_URL = "https://archives.nseindia.com/content/indices/IndexInclExcl.csv"


def _parse_nse_date_flexible(date_str: str) -> str | None:
    """Parse various NSE date formats to ISO format."""
    date_str = date_str.strip()
    if date_str in ("-", "", "NA", "None"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class IndexMembershipSource(Source):
    """Historical NIFTY index constituency.

    Unlike other sources, this doesn't fetch one date at a time.
    It downloads the full historical inclusion/exclusion file once,
    then transforms it into validity-dated intervals.

    This source is special-cased: _build_url returns the historical
    file URL regardless of date. The backfill should only call this
    source once for a given date range.
    """

    name = "nse_index_membership"
    prime_url = "https://www.nseindia.com"
    silver_table = "index_membership"
    rate_limit_rps = 1.0
    min_rows = 1  # The historical file has many rows but we check it

    class _MinimalSchema:
        """Placeholder until full schema is defined."""

        @classmethod
        def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
            return df

    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        """Return URL for the historical inclusion/exclusion file.

        This file contains ALL historical changes, so the date parameter
        is ignored. Caching ensures we only download it once.
        """
        return _INCL_EXCL_URL

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse the IndexInclExcl.csv into structured membership records.

        The file has columns like:
        Index Name, Index Date, Symbol, Industry, Reason,
        including both inclusions and exclusions.
        """
        df = pl.read_csv(
            io.BytesIO(raw.body),
            infer_schema_length=0,
            ignore_errors=True,
        )

        # Strip whitespace from column names
        df = df.rename({col: col.strip() for col in df.columns})

        # Identify column names (NSE changes these occasionally)
        index_col = _find_column(df, ["Index Name", "IndexName", "index_name"])
        date_col = _find_column(df, ["Index Date", "IndexDate", "index_date"])
        symbol_col = _find_column(df, ["Symbol", "symbol", "SYMBOL"])
        reason_col = _find_column(df, ["Reason", "reason", "REASON"])

        if not index_col or not date_col or not symbol_col or not reason_col:
            logger.error(
                "index_membership_parse_failed",
                columns=df.columns,
                msg="Could not identify required columns",
            )
            return pl.DataFrame()

        assert index_col is not None
        assert date_col is not None
        assert symbol_col is not None
        assert reason_col is not None

        records: list[dict[str, object]] = []

        for row in df.iter_rows(named=True):
            index_name = str(row.get(index_col, "")).strip()
            date_str = str(row.get(date_col, "")).strip()
            symbol = str(row.get(symbol_col, "")).strip()
            reason = str(row.get(reason_col, "")).strip().lower()

            # Filter to NIFTY indices we care about
            if not any(idx in index_name.upper() for idx in ["NIFTY 50", "NIFTY 100", "NIFTY 500"]):
                continue

            parsed_date = _parse_nse_date_flexible(date_str)
            if parsed_date is None:
                continue

            # Determine if this is an inclusion or exclusion
            is_inclusion = "inclus" in reason or "add" in reason or "new" in reason
            is_exclusion = "exclus" in reason or "remov" in reason or "drop" in reason

            if is_inclusion:
                records.append(
                    {
                        "index_name": index_name,
                        "symbol": symbol,
                        "isin": "",  # Resolved via symbol_isin_map
                        "event_type": "inclusion",
                        "event_date": parsed_date,
                    }
                )
            elif is_exclusion:
                records.append(
                    {
                        "index_name": index_name,
                        "symbol": symbol,
                        "isin": "",
                        "event_type": "exclusion",
                        "event_date": parsed_date,
                    }
                )

        if not records:
            return pl.DataFrame()

        return pl.DataFrame(records)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate index membership data."""
        issues: list[ValidationIssue] = []

        if len(df) == 0:
            return issues

        # Check for duplicate events (same index, symbol, date, event_type)
        deduped = df.unique(subset=["index_name", "symbol", "event_date", "event_type"])
        if len(deduped) < len(df):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    column=None,
                    check_name="duplicate_events",
                    rows_affected=len(df) - len(deduped),
                    message=f"{len(df) - len(deduped)} duplicate membership events",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Convert inclusion/exclusion events into validity-dated intervals.

        For each (index, symbol):
          - inclusion event → valid_from = event_date
          - next exclusion event → valid_to = event_date
          - no exclusion → valid_to = NULL (still a member)
        """
        if len(bronze) == 0:
            return bronze

        # Sort by index, symbol, date to build intervals
        df = bronze.sort(["index_name", "symbol", "event_date"])

        intervals: list[dict[str, object]] = []
        # Group by (index_name, symbol) and pair inclusions with exclusions
        for group_key, group_df in df.group_by(["index_name", "symbol"]):
            index_name = group_key[0]
            symbol = group_key[1]

            inclusions = group_df.filter(pl.col("event_type") == "inclusion").sort("event_date")
            exclusions = group_df.filter(pl.col("event_type") == "exclusion").sort("event_date")

            incl_dates = inclusions["event_date"].to_list()
            excl_dates = exclusions["event_date"].to_list()

            excl_idx = 0
            for valid_from in incl_dates:
                # Find the next exclusion after this inclusion
                valid_to = None
                while excl_idx < len(excl_dates):
                    if excl_dates[excl_idx] > valid_from:
                        valid_to = excl_dates[excl_idx]
                        excl_idx += 1
                        break
                    excl_idx += 1

                intervals.append(
                    {
                        "index_name": index_name,
                        "symbol": symbol,
                        "isin": "",  # Resolved later
                        "valid_from": valid_from,
                        "valid_to": valid_to or "",
                        "knowledge_date": valid_from,
                    }
                )

        if not intervals:
            return pl.DataFrame()

        return pl.DataFrame(intervals)


def _find_column(df: pl.DataFrame, candidates: list[str]) -> str | None:
    """Find the first matching column name from a list of candidates."""
    for col in candidates:
        if col in df.columns:
            return col
    return None
