"""NSE F&O daily bhavcopy: futures and options OHLC, OI, contracts.

URL patterns:
  - 2024-07-08 onwards (UDiFF):
    nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
  - Pre-2024-07-08 (legacy):
    nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MMM/foDDMMMYYYYbhav.csv.zip
"""

import io
import zipfile
from datetime import date

import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)

# NSE Circular Ref. No. 62424, effective 2024-07-08
_UDIFF_CUTOVER = date(2024, 7, 8)

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


class _MinimalSchema:
    """Placeholder until DerivativesSchema is extended."""

    @classmethod
    def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
        return df


class FoBhavcopySource(Source):
    """NSE F&O daily bhavcopy: futures and options OHLC, OI."""

    name = "nse_fo_daily"
    prime_url = "https://www.nseindia.com"
    silver_table = "derivatives"
    min_rows = 50
    rate_limit_rps = 1.5
    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        """Build URL for the F&O bhavcopy."""
        if target_date >= _UDIFF_CUTOVER:
            ds = target_date.strftime("%Y%m%d")
            return (
                "https://nsearchives.nseindia.com/content/fo/"
                f"BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip"
            )
        dd = target_date.strftime("%d")
        mmm = _MONTHS[target_date.month - 1]
        yyyy = target_date.strftime("%Y")
        return (
            "https://nsearchives.nseindia.com/content/historical/"
            f"DERIVATIVES/{yyyy}/{mmm}/fo{dd}{mmm}{yyyy}bhav.csv.zip"
        )

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse zipped CSV into normalised DataFrame."""
        body = raw.body
        csv_bytes: bytes

        if body[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                csv_bytes = zf.read(zf.namelist()[0])
        else:
            csv_bytes = body

        df = pl.read_csv(
            io.BytesIO(csv_bytes),
            infer_schema_length=0,
            ignore_errors=True,
        )
        df = df.rename({c: c.strip() for c in df.columns})

        if raw.date >= _UDIFF_CUTOVER:
            return self._normalise_udiff(df, raw.date)
        return self._normalise_legacy(df, raw.date)

    def _normalise_udiff(self, df: pl.DataFrame, trade_date: date) -> pl.DataFrame:
        """Normalise UDiFF F&O columns."""
        return df.select(
            [
                pl.lit(trade_date.isoformat()).alias("date"),
                pl.col("TckrSymb").str.strip_chars().alias("symbol"),
                pl.col("FinInstrmTp").str.strip_chars().alias("instrument"),
                pl.col("XpryDt").str.strip_chars().alias("expiry"),
                pl.col("StrkPric").str.strip_chars().cast(pl.Float64).alias("strike"),
                pl.col("OptnTp").str.strip_chars().alias("option_type"),
                pl.col("OpnPric").str.strip_chars().cast(pl.Float64).alias("open"),
                pl.col("HghPric").str.strip_chars().cast(pl.Float64).alias("high"),
                pl.col("LwPric").str.strip_chars().cast(pl.Float64).alias("low"),
                pl.col("ClsPric").str.strip_chars().cast(pl.Float64).alias("close"),
                pl.col("SttlmPric").str.strip_chars().cast(pl.Float64).alias("settle_price"),
                pl.col("TtlTradgVol").str.strip_chars().cast(pl.Int64).alias("volume"),
                pl.col("TtlTrfVal").str.strip_chars().cast(pl.Float64).alias("turnover"),
                pl.col("OpnIntrst").str.strip_chars().cast(pl.Int64).alias("open_interest"),
                pl.col("ChngInOpnIntrst").str.strip_chars().cast(pl.Int64).alias("change_in_oi"),
            ]
        )

    def _normalise_legacy(self, df: pl.DataFrame, trade_date: date) -> pl.DataFrame:
        """Normalise legacy F&O columns."""
        return df.select(
            [
                pl.lit(trade_date.isoformat()).alias("date"),
                pl.col("SYMBOL").str.strip_chars().alias("symbol"),
                pl.col("INSTRUMENT").str.strip_chars().alias("instrument"),
                pl.col("EXPIRY_DT").str.strip_chars().alias("expiry"),
                pl.col("STRIKE_PR").str.strip_chars().cast(pl.Float64).alias("strike"),
                pl.col("OPTION_TYP").str.strip_chars().alias("option_type"),
                pl.col("OPEN").str.strip_chars().cast(pl.Float64).alias("open"),
                pl.col("HIGH").str.strip_chars().cast(pl.Float64).alias("high"),
                pl.col("LOW").str.strip_chars().cast(pl.Float64).alias("low"),
                pl.col("CLOSE").str.strip_chars().cast(pl.Float64).alias("close"),
                pl.col("SETTLE_PR").str.strip_chars().cast(pl.Float64).alias("settle_price"),
                pl.col("CONTRACTS").str.strip_chars().cast(pl.Int64).alias("volume"),
                pl.col("VAL_INLAKH").str.strip_chars().cast(pl.Float64).alias("turnover"),
                pl.col("OPEN_INT").str.strip_chars().cast(pl.Int64).alias("open_interest"),
                pl.col("CHG_IN_OI").str.strip_chars().cast(pl.Int64).alias("change_in_oi"),
            ]
        )

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate F&O data."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        neg_strike = df.filter(pl.col("strike") < 0)
        if len(neg_strike) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="strike",
                    check_name="strike_non_negative",
                    rows_affected=len(neg_strike),
                    message=f"{len(neg_strike)} rows have negative strike",
                )
            )

        neg_oi = df.filter(pl.col("open_interest") < 0)
        if len(neg_oi) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="open_interest",
                    check_name="oi_non_negative",
                    rows_affected=len(neg_oi),
                    message=f"{len(neg_oi)} rows have negative OI",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add knowledge_date and isin placeholder."""
        if len(bronze) == 0:
            return bronze
        return bronze.with_columns(
            [
                pl.col("date").alias("knowledge_date"),
                pl.lit("").alias("isin"),
            ]
        )
