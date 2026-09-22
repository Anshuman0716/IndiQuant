"""Smoke test source for fundamentals via yfinance.

This source is strictly for smoke-testing the CLI and factor pipeline.
It writes to a separate 'fundamentals_smoke' table.
"""

from datetime import date
import io
import json

import pandas as pd
import polars as pl
import structlog
import yfinance as yf

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue
from indiquant.store.schemas import _ProvenanceMixin
import pandera.polars as pa
from pandera.typing.polars import Series

logger = structlog.get_logger(__name__)


class YFinanceFundamentalsSchema(_ProvenanceMixin):
    """Schema for yfinance smoke fundamentals."""
    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    knowledge_date: Series[str]
    quarter_end: Series[str]
    revenue: Series[float] = pa.Field(nullable=True)
    pat: Series[float] = pa.Field(nullable=True)
    total_assets: Series[float] = pa.Field(nullable=True)
    current_liabilities: Series[float] = pa.Field(nullable=True)
    interest: Series[float] = pa.Field(nullable=True)
    tax: Series[float] = pa.Field(nullable=True)
    
    class Config:
        strict = False
        coerce = True


class YFinanceFundamentalsSmokeSource(Source):
    """Fetch fundamentals from yfinance for NIFTY 500 smoke testing.
    
    Since yfinance provides full history per ticker, we download all data
    once (triggered on the first run) and return it. On subsequent days,
    we return an empty payload to avoid redundant downloads.
    """

    name = "yfinance_smoke"
    prime_url = "https://finance.yahoo.com"
    silver_table = "fundamentals_smoke"
    rate_limit_rps = 2.0
    min_rows = 0
    schema = YFinanceFundamentalsSchema  # type: ignore

    def _build_url(self, target_date: date) -> str:
        """yfinance doesn't use a single URL, but we need to return something."""
        return f"yfinance://fundamentals/{target_date.isoformat()}"
        
    def fetch(self, target_date: date, *, force: bool = False, from_cache: bool = True) -> RawPayload:
        """Override fetch to download via yfinance library instead of requests."""
        # Only fetch if it's a specific trigger date or if we haven't cached it.
        # But wait, yfinance is slow. We should only fetch once for the whole history.
        # To adapt to the daily Source contract, we will fetch data for ALL stocks
        # only when target_date == date(2024, 12, 31) (the end of the backfill).
        # For other dates, we return empty payload.
        if target_date != date(2024, 12, 31):
            from datetime import datetime, UTC
            import hashlib
            body_bytes = b"[]"
            return RawPayload(
                source=self.name,
                date=target_date,
                url="yfinance_url",
                status_code=200,
                headers={},
                body=body_bytes,
                fetched_at=datetime.now(UTC).isoformat(),
                raw_hash=hashlib.sha256(body_bytes).hexdigest(),
                from_cache=False,
            )
            
        logger.info("yfinance_smoke_fetch", msg="Downloading full history from yfinance for NIFTY 50")
        
        # We limit to NIFTY 50 for the smoke test to save time.
        # NIFTY 50 symbols (a representative subset)
        symbols = [
            "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", 
            "ITC", "SBIN", "BHARTIARTL", "HINDUNILVR", "L&T"
        ]
        
        results = []
        for sym in symbols:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                
                # Fetch quarterly financials
                qf = ticker.quarterly_financials
                qbs = ticker.quarterly_balance_sheet
                
                if qf is None or qf.empty:
                    continue
                    
                # Convert to structured list of dicts
                for dt in qf.columns:
                    q_date = dt.date().isoformat()
                    
                    try:
                        revenue = float(qf.loc["Total Revenue", dt]) if "Total Revenue" in qf.index else 0.0
                        pat = float(qf.loc["Net Income", dt]) if "Net Income" in qf.index else 0.0
                        interest = float(qf.loc["Interest Expense", dt]) if "Interest Expense" in qf.index else 0.0
                        tax = float(qf.loc["Tax Provision", dt]) if "Tax Provision" in qf.index else 0.0
                    except (KeyError, TypeError, ValueError):
                        continue
                        
                    total_assets = 0.0
                    current_liabilities = 0.0
                    
                    if qbs is not None and dt in qbs.columns:
                        try:
                            total_assets = float(qbs.loc["Total Assets", dt]) if "Total Assets" in qbs.index else 0.0
                            current_liabilities = float(qbs.loc["Current Liabilities", dt]) if "Current Liabilities" in qbs.index else 0.0
                        except (KeyError, TypeError, ValueError):
                            pass
                            
                    results.append({
                        "symbol": sym,
                        "quarter_end": q_date,
                        "revenue": revenue,
                        "pat": pat,
                        "interest": interest,
                        "tax": tax,
                        "total_assets": total_assets,
                        "current_liabilities": current_liabilities,
                    })
            except Exception as e:
                logger.warning("yfinance_fetch_failed", symbol=sym, error=str(e))
                
        from datetime import datetime, UTC
        import hashlib
        
        body_bytes = json.dumps(results).encode("utf-8")
        raw_hash = hashlib.sha256(body_bytes).hexdigest()
        
        return RawPayload(
            source=self.name,
            date=target_date,
            url="yfinance_url",
            status_code=200,
            headers={},
            body=body_bytes,
            fetched_at=datetime.now(UTC).isoformat(),
            raw_hash=raw_hash,
            from_cache=False,
        )

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse JSON response into structured DataFrame."""
        if not raw.body:
            return pl.DataFrame()
            
        data = json.loads(raw.body.decode("utf-8"))
        if not data:
            return pl.DataFrame()
            
        return pl.DataFrame(data)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Map symbols to ISINs and add knowledge_date."""
        if len(bronze) == 0:
            return bronze
            
        # Add a synthetic knowledge_date (approx 45 days after quarter end)
        # In reality, knowledge_date comes from the NSE filing timestamp.
        df = bronze.with_columns(
            (pl.col("quarter_end").cast(pl.Date) + pl.duration(days=45)).cast(pl.Utf8).alias("knowledge_date")
        )

        import duckdb
        try:
            with self.lakehouse.connection() as cur:
                eq_path = (self.lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
                mapping_query = f"""
                WITH mapping AS (
                    SELECT isin, symbol
                    FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
                    GROUP BY isin, symbol
                )
                SELECT d.*, COALESCE(m.isin, '') AS isin
                FROM df d
                LEFT JOIN mapping m ON d.symbol = m.symbol
                """
                mapped_df = cur.execute(mapping_query).pl()
                
                # Filter out those we couldn't map
                mapped_df = mapped_df.filter(pl.col("isin") != "")
                
                # Deduplicate just in case multiple ISINs matched
                return mapped_df.unique(subset=["isin", "quarter_end"])
        except duckdb.IOException:
            logger.warning("yfinance_isin_mapping_failed")
            return df.with_columns(pl.lit("").alias("isin"))
