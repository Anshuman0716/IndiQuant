"""Bulk and Block deals.

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

class BulkBlockDealsSource(Source):
    name = "nse_bulk_block_deals"
    silver_table = "bulk_block_deals"
    min_rows = 0
    schema = _MinimalSchema  # type: ignore[assignment]

    def fetch(self, target_date: date) -> RawPayload:
        seed = target_date.toordinal()
        np.random.seed(seed)
        
        # Randomly decide if there are any deals today
        num_deals = np.random.randint(0, 10)
        data = []
        for i in range(num_deals):
            data.append({
                "date": target_date.isoformat(),
                "symbol": f"MOCK{i}",
                "client_name": "MOCK FUND",
                "deal_type": np.random.choice(["BUY", "SELL"]),
                "quantity": int(np.random.randint(100000, 5000000)),
                "price": float(np.random.uniform(50, 3000))
            })
        import json
        body = json.dumps(data).encode("utf-8")
        
        return RawPayload(
            source=self.name,
            date=target_date,
            url="synthetic://bulk_block",
            status_code=200,
            headers={},
            body=body,
            fetched_at="2020-01-01T00:00:00Z",
            raw_hash="synthetic",
            from_cache=False,
        )

    def _build_url(self, target_date: date) -> str:
        return "synthetic://bulk_block"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        import json
        data = json.loads(raw.body.decode("utf-8"))
        if not data:
            return pl.DataFrame(schema={"date": pl.Utf8, "symbol": pl.Utf8, "client_name": pl.Utf8, "deal_type": pl.Utf8, "quantity": pl.Int64, "price": pl.Float64})
        df = pl.DataFrame(data)
        return df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        if len(bronze) == 0:
            return bronze.with_columns(pl.lit("2000-01-01").alias("knowledge_date"))
        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
