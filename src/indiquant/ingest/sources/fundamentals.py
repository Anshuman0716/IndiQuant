"""Fundamental financial metrics.

Implementation: Synthetic/Mock generator for demonstration purposes.
Historical PIT-correct endpoints are WAF-blocked.
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

class FundamentalsSource(Source):
    name = "nse_fundamentals"
    silver_table = "fundamentals"
    min_rows = 0
    schema = _MinimalSchema  # type: ignore[assignment]

    def fetch(self, target_date: date) -> RawPayload:
        seed = target_date.toordinal()
        np.random.seed(seed)
        
        data = []
        for symbol in ["RELIANCE", "TCS", "HDFCBANK", "INFY"]:
            data.append({
                "date": target_date.isoformat(),
                "symbol": symbol,
                "revenue": float(np.random.uniform(1e9, 1e11)),
                "net_profit": float(np.random.uniform(1e8, 1e10)),
                "ebitda": float(np.random.uniform(5e8, 2e10))
            })
        import json
        body = json.dumps(data).encode("utf-8")
        
        return RawPayload(
            source=self.name,
            date=target_date,
            url="synthetic://fundamentals",
            status_code=200,
            headers={},
            body=body,
            fetched_at="2020-01-01T00:00:00Z",
            raw_hash="synthetic",
            from_cache=False,
        )

    def _build_url(self, target_date: date) -> str:
        return "synthetic://fundamentals"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        import json
        data = json.loads(raw.body.decode("utf-8"))
        if not data:
            return pl.DataFrame(schema={"date": pl.Utf8, "symbol": pl.Utf8, "revenue": pl.Float64, "net_profit": pl.Float64, "ebitda": pl.Float64})
        return pl.DataFrame(data)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        if len(bronze) == 0:
            return bronze.with_columns(pl.lit("2000-01-01").alias("knowledge_date"))
        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
