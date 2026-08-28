"""Quarterly shareholding patterns.

Source: NSE corporate filings / SEBI XBRL submissions.
Published quarterly with a ~21 day lag after quarter end.

knowledge_date = filing_date (NOT quarter_end) for PIT compliance.
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


class ShareholdingSource(Source):
    """Source for quarterly shareholding patterns."""

    name = "nse_shareholding"
    prime_url = "https://www.nseindia.com"
    schema = _MinimalSchema  # type: ignore[assignment]
    silver_table = "shareholding"
    rate_limit_rps = 1.0
    min_rows = 1

    def _build_url(self, target_date: date) -> str:
        """Build the URL for corporate shareholding."""
        ds = target_date.strftime("%d-%m-%Y")
        return (
            "https://www.nseindia.com/api/corporates-shareholding?"
            f"index=equities&from_date={ds}&to_date={ds}"
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
            "shareholdingDate": "quarter_end",
            "submissionDate": "filing_date",
            "promoterAndPromoterGroup": "promoter_pct",
            "publicShareholding": "public_pct",
            "fii": "fii_pct",
            "dii": "dii_pct",
        }

        for col in cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))

        df = df.rename(cols)

        df = df.with_columns(
            [
                pl.lit("").alias("isin"),
                pl.col("promoter_pct").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.col("fii_pct").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.col("dii_pct").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.col("public_pct").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.col("quarter_end").str.strptime(pl.Date, "%d-%b-%Y", strict=False),
                pl.col("filing_date").str.strptime(pl.Date, "%d-%b-%Y", strict=False),
            ]
        )

        parsed_df = df.select(
            [
                "symbol",
                "quarter_end",
                "filing_date",
                "promoter_pct",
                "fii_pct",
                "dii_pct",
                "public_pct",
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
                 AND p.filing_date >= m.first_seen
                 AND p.filing_date <= m.last_seen
                """
                mapped_df = cur.execute(mapping_query).pl()
                return mapped_df.group_by(["symbol", "filing_date"]).first()
        except duckdb.IOException:
            return parsed_df.with_columns(pl.lit("").alias("isin"))

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate percentages are in [0, 100] and sum to ~100."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        pct_cols = ["promoter_pct", "fii_pct", "dii_pct", "public_pct"]
        for col in pct_cols:
            invalid = df.filter((pl.col(col) < 0) | (pl.col(col) > 100))
            if len(invalid) > 0:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        column=col,
                        check_name="pct_bounds",
                        rows_affected=len(invalid),
                        message=f"Found {len(invalid)} rows with {col} out of bounds",
                    )
                )

        total_pct = df.with_columns(
            (
                pl.col("promoter_pct")
                + pl.col("fii_pct")
                + pl.col("dii_pct")
                + pl.col("public_pct")
            ).alias("total")
        )

        invalid_sum = total_pct.filter((pl.col("total") < 98) | (pl.col("total") > 102))
        if len(invalid_sum) > 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    column="promoter_pct",
                    check_name="pct_sum",
                    rows_affected=len(invalid_sum),
                    message=f"Found {len(invalid_sum)} rows with sum not approx 100",
                )
            )

        # Uniqueness check on (isin, filing_date)
        duplicates = df.group_by(["isin", "filing_date"]).len().filter(pl.col("len") > 1)
        if len(duplicates) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="isin",
                    check_name="unique_isin_knowledge_date",
                    rows_affected=len(duplicates),
                    message=f"Found {len(duplicates)} duplicate (isin, filing_date) pairs",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Set knowledge_date = filing_date for PIT compliance."""
        if len(bronze) == 0:
            return bronze
        return bronze.with_columns(pl.col("filing_date").alias("knowledge_date"))
