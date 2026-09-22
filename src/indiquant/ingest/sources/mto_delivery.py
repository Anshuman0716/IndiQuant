"""MTO Delivery data source."""
from datetime import date
import polars as pl
import structlog
import io
from indiquant.ingest.models import RawPayload, ValidationIssue
from indiquant.ingest.base import Source
class _MinimalSchema:
    pass

class MtoDeliverySource(Source):
    name = "nse_mto_delivery"
    prime_url = "https://www.nseindia.com"
    schema = _MinimalSchema  # type: ignore[assignment]
    silver_table = "mto_delivery"
    rate_limit_rps = 1.0
    min_rows = 100

    def _build_url(self, target_date: date) -> str:
        ds = target_date.strftime("%d%m%Y")
        return f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{ds}.DAT"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        body = raw.body.decode("utf-8", errors="replace")
        
        # MTO format:
        # Record Type, Sr No, Name of Security, Segment, Traded Qty, Deliverable Qty, % Dly Qty to Traded Qty
        lines = []
        for line in body.split("\n"):
            line = line.strip()
            # Ignore headers (e.g. starts with "Record Type" or "01" etc. or comments)
            if line.startswith("20,") and "EQ" in line:  # Record Type 20 is typically normal equities
                lines.append(line)
        
        if not lines:
            return pl.DataFrame({"date": [], "symbol": [], "traded_qty": [], "delivery_qty": [], "delivery_pct": []})
            
        csv_data = "\n".join(lines)
        df = pl.read_csv(
            io.StringIO(csv_data),
            has_header=False,
            new_columns=["rec_type", "sr_no", "symbol", "segment", "traded_qty", "delivery_qty", "delivery_pct"]
        )
        
        df = df.select([
            pl.col("symbol").str.strip_chars(),
            pl.lit(raw.date.isoformat()).alias("date"),
            pl.col("traded_qty").cast(pl.Int64),
            pl.col("delivery_qty").cast(pl.Int64),
            pl.col("delivery_pct").cast(pl.Float64)
        ])
        return df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        df = bronze.with_columns(
            pl.col("date").alias("knowledge_date"),
            pl.lit("").alias("isin")
        )
        return df
