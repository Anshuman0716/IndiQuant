"""Shareholding patterns.

Implementation: Synthetic/Mock generator for demonstration purposes.
Historical endpoints are WAF-blocked.
"""

from datetime import date
import polars as pl
import numpy as np

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

class _MinimalSchema:
    @classmethod
    def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
        return df

class ShareholdingSource(Source):
    name = "nse_shareholding"
    silver_table = "shareholding"
    min_rows = 0
    schema = _MinimalSchema  # type: ignore[assignment]

    def fetch(self, target_date: date) -> RawPayload:
        seed = target_date.toordinal()
        np.random.seed(seed)
        
        data = []
        # Mock shareholding for some standard symbols
        for symbol in ["RELIANCE", "TCS", "HDFCBANK", "INFY"]:
            data.append({
                "date": target_date.isoformat(),
                "symbol": symbol,
                "promoter_holding": float(np.random.uniform(30, 75)),
                "public_holding": float(np.random.uniform(25, 70))
            })
        import json
        body = json.dumps(data).encode("utf-8")
        
        return RawPayload(
            source=self.name,
            date=target_date,
            url="synthetic://shareholding",
            status_code=200,
            headers={},
            body=body,
            fetched_at="2020-01-01T00:00:00Z",
            raw_hash="synthetic",
            from_cache=False,
        )

    def _build_url(self, target_date: date) -> str:
        return "synthetic://shareholding"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        import json
        data = json.loads(raw.body.decode("utf-8"))
        if not data:
            return pl.DataFrame(schema={"date": pl.Utf8, "symbol": pl.Utf8, "promoter_holding": pl.Float64, "public_holding": pl.Float64})
        return pl.DataFrame(data)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        if len(bronze) == 0:
            return bronze.with_columns(pl.lit("2000-01-01").alias("knowledge_date"))
        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
