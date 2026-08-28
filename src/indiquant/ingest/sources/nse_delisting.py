"""NSE Delisting Notices.

Provides explicit dates and reasons for security delistings.
"""

from datetime import date
from typing import Any

import pandas as pd
import polars as pl
import structlog
from pandera.typing.polars import Series

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue
from indiquant.store.schemas import _ProvenanceMixin
import pandera.polars as pa


class DelistingSchema(_ProvenanceMixin):
    """Explicit delisting events."""
    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    symbol: Series[str]
    delisting_date: Series[str]
    reason: Series[str]  # e.g. "compulsory", "voluntary_exit", "merger_acquisition"


class NseDelistingSource(Source):
    """NSE delisting data source.
    
    Parses regulation notices or exchange CSVs containing delisting events.
    """

    name = "nse_delisting"
    prime_url = "https://www.nseindia.com"
    silver_table = "delistings"
    rate_limit_rps = 1.0
    min_rows = 1
    schema = DelistingSchema

    def _build_url(self, target_date: date) -> str:
        """API URL for delisting data."""
        # Note: in a real implementation, this would point to the specific NSE API
        # For now, it returns a placeholder or empty on most days.
        return f"https://www.nseindia.com/api/delisting?date={target_date.isoformat()}"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse response."""
        # Simulated parsing since we don't have the live API yet.
        return pl.DataFrame(
            schema={
                "isin": pl.Utf8,
                "symbol": pl.Utf8,
                "delisting_date": pl.Utf8,
                "reason": pl.Utf8,
            }
        )

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        if len(bronze) == 0:
            return bronze
            
        return bronze.with_columns(
            pl.col("delisting_date").alias("knowledge_date")
        )
