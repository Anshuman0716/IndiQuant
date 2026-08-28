"""Quarterly financial results from NSE corporate filings.

Source: NSE corporate results API.
Published with a lag after quarter end.

knowledge_date = result_date (the board meeting/publication date),
NOT quarter_end. This is critical for PIT compliance.
"""

import json
from datetime import date

import polars as pl

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue


class _MinimalSchema:
    """Placeholder schema."""

    @classmethod
    def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
        return df


class FundamentalsSource(Source):
    """Source for quarterly financial results."""

    name = "nse_fundamentals"
    prime_url = "https://www.nseindia.com"
    schema = _MinimalSchema  # type: ignore[assignment]
    silver_table = "fundamentals"
    rate_limit_rps = 1.0
    min_rows = 1

    def _build_url(self, target_date: date) -> str:
        """Build the URL for corporate financial results."""
        ds = target_date.strftime("%d-%m-%Y")
        return (
            "https://www.nseindia.com/api/corporates-financial-results?"
            f"index=equities&from_date={ds}&to_date={ds}&type=quarterly"
        )

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse JSON response into a DataFrame."""
        if not raw.body:
            return pl.DataFrame()

        try:
            data = json.loads(raw.body.decode("utf-8"))
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
        except json.JSONDecodeError:
            return pl.DataFrame()

        if not data:
            return pl.DataFrame()

        df = pl.DataFrame(data)
        if len(df) == 0:
            return df

        df = df.rename({c: c.strip() for c in df.columns})

        cols = {
            "symbol": "symbol",
            "quarter": "quarter_end",
            "broadcastDate": "result_date",
            "income": "revenue",
            "netProfit": "pat",
            "eps": "eps",
            "faceValue": "face_value",
        }

        for col in cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))

        df = df.rename(cols)

        df = df.with_columns(
            [
                pl.lit("").alias("isin"),
                pl.col("revenue").cast(pl.Float64, strict=False),
                pl.col("pat").cast(pl.Float64, strict=False),
                pl.col("eps").cast(pl.Float64, strict=False),
                pl.col("face_value").cast(pl.Float64, strict=False),
                pl.col("quarter_end").str.strptime(pl.Date, "%d-%b-%Y", strict=False),
                pl.col("result_date").str.strptime(pl.Date, "%d-%b-%Y", strict=False),
            ]
        )

        parsed_df = df.select(
            [
                "symbol",
                "quarter_end",
                "result_date",
                "revenue",
                "pat",
                "eps",
                "face_value",
            ]
        )

        import duckdb

        try:
            with self.lakehouse.connection() as cur:
                eq_path = (self.lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
                mapping_query = f"""
                WITH mapping AS (
                    SELECT isin, symbol, MIN(date) as first_seen, MAX(date) as last_seen
                    FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
                    GROUP BY isin, symbol
                )
                SELECT p.*, COALESCE(m.isin, '') AS isin
                FROM parsed_df p
                LEFT JOIN mapping m
                  ON p.symbol = m.symbol
                 AND p.result_date >= m.first_seen
                 AND p.result_date <= m.last_seen
                """
                mapped_df = cur.execute(mapping_query).pl()
                # Deduplicate if overlapping reuses
                return mapped_df.group_by(["symbol", "result_date"]).first()
        except duckdb.IOException:
            # Fallback if equity_daily doesn't exist
            return parsed_df.with_columns(pl.lit("").alias("isin"))

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate reasonable EPS values."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        invalid_eps = df.filter(pl.col("eps").abs() > 100000)
        if len(invalid_eps) > 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    column="eps",
                    check_name="eps_bounds",
                    rows_affected=len(invalid_eps),
                    message=f"Found {len(invalid_eps)} rows with unreasonable EPS > 100000",
                )
            )

        # Uniqueness check on (isin, result_date) to prevent duplicates reaching as_known_on
        duplicates = df.group_by(["isin", "result_date"]).len().filter(pl.col("len") > 1)
        if len(duplicates) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="isin",
                    check_name="unique_isin_knowledge_date",
                    rows_affected=len(duplicates),
                    message=f"Found {len(duplicates)} duplicate (isin, result_date) pairs",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Set knowledge_date = result_date for PIT compliance."""
        if len(bronze) == 0:
            return bronze
        return bronze.with_columns(pl.col("result_date").alias("knowledge_date"))
