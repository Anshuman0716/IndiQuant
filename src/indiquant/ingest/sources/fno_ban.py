"""F&O Ban list data source."""
from datetime import date
import polars as pl
import structlog
from indiquant.ingest.models import RawPayload, ValidationIssue
from indiquant.ingest.base import Source
class _MinimalSchema:
    pass

class FnoBanSource(Source):
    name = "nse_fno_ban"
    prime_url = "https://www.nseindia.com"
    schema = _MinimalSchema  # type: ignore[assignment]
    silver_table = "fno_ban"
    rate_limit_rps = 1.0
    min_rows = 1

    def _build_url(self, target_date: date) -> str:
        ds = target_date.strftime("%d%m%Y")
        return f"https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_{ds}.csv"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        body = raw.body.decode("utf-8", errors="replace").strip()
        lines = body.split("\n")
        symbols = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 2:
                sym = parts[1].strip()
                if sym:
                    symbols.append(sym)
                    
        return pl.DataFrame({
            "date": [raw.date.isoformat()] * len(symbols),
            "symbol": symbols
        })

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        df = bronze.with_columns(
            pl.col("date").alias("knowledge_date"),
            pl.lit("").alias("isin")
        )
        return df
