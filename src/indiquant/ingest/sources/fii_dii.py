"""FII/DII daily cash market activity.

Source: NSDL/SEBI daily FII/DII reports.
URL: https://archives.nseindia.com/content/fo/fii_stats_DDMMMYYYY.xls (historical)
     or NSE API for recent data.
"""

import json
from datetime import date

import polars as pl

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue


class _MinimalSchema:
    """Placeholder until schema is extended."""

    @classmethod
    def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
        return df


class FiiDiiSource(Source):
    """FII/DII flow source."""

    name = "nse_fii_dii"
    prime_url = "https://www.nseindia.com"
    silver_table = "institutional_flows"
    min_rows = 1
    rate_limit_rps = 1.0
    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        """Build URL for FII/DII."""
        # For historical dates, NSE uses XLS which requires a different parser.
        # This implementation uses the live API endpoint for simplicity, which
        # typically only returns recent data. Historical ingestion requires
        # the XLS parser (TODO).
        return "https://www.nseindia.com/api/fiidiiTradeReact"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse the JSON response."""
        if not raw.body:
            return pl.DataFrame()

        try:
            data = json.loads(raw.body.decode("utf-8"))
        except json.JSONDecodeError:
            return pl.DataFrame()

        records = data if isinstance(data, list) else data.get("data", [])
        if not records:
            return pl.DataFrame()

        df = pl.DataFrame(records)
        df = df.select(
            [
                pl.lit(raw.date.isoformat()).alias("date"),
                pl.col("category").str.strip_chars(),
                pl.col("buyValue").cast(pl.Float64).alias("buy_value"),
                pl.col("sellValue").cast(pl.Float64).alias("sell_value"),
                pl.col("netValue").cast(pl.Float64).alias("net_value"),
            ]
        )

        return df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate flow data."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        neg_buy = df.filter(pl.col("buy_value") < 0)
        if len(neg_buy) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="buy_value",
                    check_name="buy_value_non_negative",
                    rows_affected=len(neg_buy),
                    message=f"{len(neg_buy)} rows have negative buy_value",
                )
            )

        neg_sell = df.filter(pl.col("sell_value") < 0)
        if len(neg_sell) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="sell_value",
                    check_name="sell_value_non_negative",
                    rows_affected=len(neg_sell),
                    message=f"{len(neg_sell)} rows have negative sell_value",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add metadata."""
        if len(bronze) == 0:
            return bronze

        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
