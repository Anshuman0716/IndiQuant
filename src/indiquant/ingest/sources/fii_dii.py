"""FII/DII daily cash market activity.

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

class FiiDiiSource(Source):
    name = "nse_fii_dii"
    silver_table = "institutional_flows"
    min_rows = 1
    schema = _MinimalSchema  # type: ignore[assignment]

    def fetch(self, target_date: date) -> RawPayload:
        # Generate synthetic data based on date to be deterministic
        seed = target_date.toordinal()
        np.random.seed(seed)
        
        fii_buy = float(np.random.uniform(5000, 20000))
        fii_sell = float(np.random.uniform(5000, 20000))
        dii_buy = float(np.random.uniform(3000, 15000))
        dii_sell = float(np.random.uniform(3000, 15000))
        
        data = [
            {"date": target_date.isoformat(), "category": "FII/FPI", "buy_value": fii_buy, "sell_value": fii_sell, "net_value": fii_buy - fii_sell},
            {"date": target_date.isoformat(), "category": "DII", "buy_value": dii_buy, "sell_value": dii_sell, "net_value": dii_buy - dii_sell},
        ]
        import json
        body = json.dumps(data).encode("utf-8")
        
        return RawPayload(
            source=self.name,
            date=target_date,
            url="synthetic://fii_dii",
            status_code=200,
            headers={},
            body=body,
            fetched_at="2020-01-01T00:00:00Z",
            raw_hash="synthetic",
            from_cache=False,
        )

    def _build_url(self, target_date: date) -> str:
        return "synthetic://fii_dii"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        import json
        data = json.loads(raw.body.decode("utf-8"))
        df = pl.DataFrame(data)
        return df.select([
            pl.col("date"),
            pl.col("category"),
            pl.col("buy_value"),
            pl.col("sell_value"),
            pl.col("net_value"),
        ])

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
