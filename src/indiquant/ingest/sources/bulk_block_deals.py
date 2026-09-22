"""NSE bulk and block deals.

Bulk deal: single trade >= 0.5% of equity shares.
Block deal: single trade >= 5 lakh shares or Rs 10 crore.

URL patterns:
  Bulk: https://nsearchives.nseindia.com/content/equities/bulk.csv
  Block: https://nsearchives.nseindia.com/content/equities/block.csv
  (These give current day; for historical, NSE API is used)
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


class BulkBlockDealsSource(Source):
    """Source for NSE bulk and block deals."""

    name = "nse_bulk_block_deals"
    prime_url = "https://www.nseindia.com"
    schema = _MinimalSchema  # type: ignore[assignment]
    silver_table = "bulk_block_deals"
    rate_limit_rps = 1.0
    min_rows = 1

    def _build_url(self, target_date: date) -> str:
        """Build the URL for the given date."""
        return "https://www.nseindia.com/api/snapshot-capital-market-largedeal"

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

        # The API returns independent lists for different deal types:
        # e.g., 'BULK_DEALS_DATA', 'SHORT_DEALS_DATA', 'BLOCK_DEALS_DATA'
        records = []
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list) and key.endswith("_DATA"):
                    # Add a tag for the source array if dealType is missing
                    for row in val:
                        row["source_array"] = key
                        records.append(row)
        elif isinstance(data, list):
            records = data

        if not records:
            return pl.DataFrame()

        df = pl.DataFrame(records)
        if len(df) == 0:
            return df

        # Normalize column names
        df = df.rename({c: c.strip() for c in df.columns})

        # Expected fields: symbol, dealDate, clientName, dealType, quantity, tradePrice
        cols_needed = {
            "date": "date",
            "symbol": "symbol",
            "buySell": "deal_type",
            "clientName": "client_name",
            "qty": "quantity",
            "watp": "price",
        }

        for col in cols_needed:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))

        df = df.rename(cols_needed)

        # Parse numeric and add missing columns
        df = df.with_columns(
            [
                pl.col("date").str.strptime(pl.Date, "%d-%b-%Y", strict=False),
                pl.lit("").alias("isin"),
                pl.col("quantity").cast(pl.Float64, strict=False),
                pl.col("price").cast(pl.Float64, strict=False),
            ]
        )

        df = df.with_columns((pl.col("quantity") * pl.col("price")).alias("turnover"))

        return df.select(
            [
                "date",
                "symbol",
                "isin",
                "deal_type",
                "client_name",
                "quantity",
                "price",
                "turnover",
            ]
        )

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate quantity and price > 0."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        invalid_qty = df.filter(pl.col("quantity") <= 0)
        if len(invalid_qty) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="quantity",
                    check_name="quantity_positive",
                    rows_affected=len(invalid_qty),
                    message=f"Found {len(invalid_qty)} rows with quantity <= 0",
                )
            )

        invalid_price = df.filter(pl.col("price") <= 0)
        if len(invalid_price) > 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column="price",
                    check_name="price_positive",
                    rows_affected=len(invalid_price),
                    message=f"Found {len(invalid_price)} rows with price <= 0",
                )
            )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add PIT knowledge_date = date."""
        if len(bronze) == 0:
            return bronze
        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
