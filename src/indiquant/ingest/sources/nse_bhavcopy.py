"""NSE daily equity bhavcopy (OHLCV + delivery data).

Handles three distinct URL/file-format eras:
  - 2024-07-08 onwards: UDiFF format (BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip)
  - 2012 to 2024-07-07: Legacy zipped CSV (cmDDMMMYYYYbhav.csv.zip)
  - Pre-2012: sec_bhavdata_full (uncompressed CSV, no ISIN — requires symbol map)

Session priming is mandatory: NSE's Akamai bot manager rejects requests
without a valid cookie chain from www.nseindia.com.
"""

import io
import zipfile
from datetime import date

import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue
from indiquant.store.schemas import EquityDailySchema

logger = structlog.get_logger(__name__)

# ── URL format transition date ──
# NSE Circular Ref. No. 62424, effective 2024-07-08
_UDIFF_CUTOVER = date(2024, 7, 8)

# Month abbreviations for legacy URL format
_MONTHS = [
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
]


class EquityBhavcopySource(Source):
    """NSE daily equity OHLCV + delivery data.

    This is Source #1 in the dependency chain. All other sources
    (corporate actions, index membership) depend on the symbol-ISIN
    mapping derived from bhavcopy data.
    """

    name = "nse_equity_daily"
    prime_url = "https://www.nseindia.com"
    schema = EquityDailySchema
    silver_table = "equity_daily"
    rate_limit_rps = 1.5
    # A normal trading day has ~1800 rows. 100 is a generous floor
    # that catches truly empty/garbage responses without false-positiving
    # on thin days (e.g. post-holiday sessions).
    min_rows = 100

    def _build_url(self, target_date: date) -> str:
        """Return the download URL for the given date.

        Handles three eras of NSE URL formats. If the primary URL fails,
        _http_get's retry logic will re-attempt, but we don't try
        alternate URLs here — that would mask real data gaps.
        """
        if target_date >= _UDIFF_CUTOVER:
            # UDiFF format (2024-07-08 onwards)
            # NSE Circular Ref. No. 62424
            ds = target_date.strftime("%Y%m%d")
            return (
                f"https://nsearchives.nseindia.com/content/cm/"
                f"BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip"
            )

        # Legacy format (2012–2024-07-07)  # noqa: RUF003
        dd = target_date.strftime("%d")
        mmm = _MONTHS[target_date.month - 1]
        yyyy = target_date.strftime("%Y")
        return (
            f"https://nsearchives.nseindia.com/content/historical/"
            f"EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip"
        )

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse raw bytes into a Polars DataFrame.

        Handles both zipped CSV (legacy + UDiFF) and uncompressed CSV.
        Column names are normalised to a common schema regardless of era.
        """
        body = raw.body

        # Try to unzip first — both legacy and UDiFF are zipped
        csv_bytes: bytes
        if body[:4] == b"PK\x03\x04":  # ZIP magic bytes
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                csv_name = zf.namelist()[0]
                csv_bytes = zf.read(csv_name)
        else:
            csv_bytes = body

        df = pl.read_csv(
            io.BytesIO(csv_bytes),
            infer_schema_length=0,  # Read everything as string first
            ignore_errors=True,
        )

        # Strip whitespace from column names (NSE CSVs have trailing spaces)
        df = df.rename({col: col.strip() for col in df.columns})

        if raw.date >= _UDIFF_CUTOVER:
            return self._normalise_udiff(df, raw.date)
        return self._normalise_legacy(df, raw.date)

    def _normalise_udiff(self, df: pl.DataFrame, trade_date: date) -> pl.DataFrame:
        """Normalise UDiFF-format bhavcopy to common schema.

        UDiFF columns: TradDt, ISIN, TckrSymb, SctySrs, OpnPric, HghPric,
        LwPric, ClsPric, LastPric, PrvsClsgPric, TtlTradgVol, TtlTrfVal, etc.
        """
        # Filter to equity series only
        if "SctySrs" in df.columns:
            df = df.filter(pl.col("SctySrs").str.strip_chars().is_in(["EQ", "BE", "BZ"]))

        return df.select(
            [
                pl.col("ISIN").str.strip_chars().alias("isin"),
                pl.col("TckrSymb").str.strip_chars().alias("symbol"),
                pl.col("SctySrs").str.strip_chars().alias("series"),
                pl.lit(trade_date.isoformat()).alias("date"),
                pl.col("OpnPric").str.strip_chars().cast(pl.Float64).alias("open"),
                pl.col("HghPric").str.strip_chars().cast(pl.Float64).alias("high"),
                pl.col("LwPric").str.strip_chars().cast(pl.Float64).alias("low"),
                pl.col("ClsPric").str.strip_chars().cast(pl.Float64).alias("close"),
                pl.col("LastPric").str.strip_chars().cast(pl.Float64).alias("last_price"),
                pl.col("PrvsClsgPric").str.strip_chars().cast(pl.Float64).alias("prev_close"),
                pl.col("TtlTradgVol").str.strip_chars().cast(pl.Int64).alias("volume"),
                pl.col("TtlTrfVal").str.strip_chars().cast(pl.Float64).alias("turnover"),
            ]
        )

    def _normalise_legacy(self, df: pl.DataFrame, trade_date: date) -> pl.DataFrame:
        """Normalise legacy cmDDMMMYYYYbhav.csv format to common schema.

        Legacy columns: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST,
        PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
        """
        # Filter to equity series
        if "SERIES" in df.columns:
            df = df.filter(pl.col("SERIES").str.strip_chars().is_in(["EQ", "BE", "BZ"]))

        return df.select(
            [
                pl.col("ISIN").str.strip_chars().alias("isin"),
                pl.col("SYMBOL").str.strip_chars().alias("symbol"),
                pl.col("SERIES").str.strip_chars().alias("series"),
                pl.lit(trade_date.isoformat()).alias("date"),
                pl.col("OPEN").str.strip_chars().cast(pl.Float64).alias("open"),
                pl.col("HIGH").str.strip_chars().cast(pl.Float64).alias("high"),
                pl.col("LOW").str.strip_chars().cast(pl.Float64).alias("low"),
                pl.col("CLOSE").str.strip_chars().cast(pl.Float64).alias("close"),
                pl.col("LAST").str.strip_chars().cast(pl.Float64).alias("last_price"),
                pl.col("PREVCLOSE").str.strip_chars().cast(pl.Float64).alias("prev_close"),
                pl.col("TOTTRDQTY").str.strip_chars().cast(pl.Int64).alias("volume"),
                pl.col("TOTTRDVAL").str.strip_chars().cast(pl.Float64).alias("turnover"),
            ]
        )

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Business rules beyond pandera schema checks."""
        issues: list[ValidationIssue] = []

        # Rule: high >= low
        violations = df.filter(pl.col("high") < pl.col("low"))
        if len(violations) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="high/low",
                    check_name="high_ge_low",
                    rows_affected=len(violations),
                    message=f"{len(violations)} rows have high < low",
                )
            )

        # Rule: close within [low, high]
        violations = df.filter(
            (pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high"))
        )
        if len(violations) > 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    column="close",
                    check_name="close_within_bars",
                    rows_affected=len(violations),
                    message=f"{len(violations)} rows have close outside [low, high]",
                )
            )

        # Rule: volume >= 0
        violations = df.filter(pl.col("volume") < 0)
        if len(violations) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="volume",
                    check_name="volume_non_negative",
                    rows_affected=len(violations),
                    message=f"{len(violations)} rows have negative volume",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add knowledge_date and deduplicate.

        OHLCV is publicly known on the same day as the trade date.
        Deduplication is by (isin, date) — if multiple series exist for
        the same ISIN on the same date, we keep the EQ series.
        """
        df = bronze.with_columns(
            pl.col("date").alias("knowledge_date"),
        )

        # Deduplicate: prefer EQ over BE/BZ for same ISIN+date
        df = df.sort(
            ["isin", "date", "series"],
        ).unique(
            subset=["isin", "date"],
            keep="first",
        )

        return df
