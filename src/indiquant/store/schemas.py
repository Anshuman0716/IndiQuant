import pandera.polars as pa
import polars as pl
from pandera.typing.polars import Series


class _ProvenanceMixin(pa.DataFrameModel):
    """Provenance columns present on every silver table."""

    source: Series[str] = pa.Field(description="Source identifier")
    ingested_at: Series[str] = pa.Field(description="UTC ISO timestamp of ingestion")
    raw_hash: Series[str] = pa.Field(description="SHA-256 of raw payload")
    knowledge_date: Series[str] = pa.Field(
        description="Date this data became publicly known. PIT queries filter on this."
    )


class EquityDailySchema(_ProvenanceMixin):
    """OHLCV daily bars for NSE/BSE equities."""

    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    date: Series[str]
    open: Series[float] = pa.Field(gt=0.0)
    high: Series[float] = pa.Field(gt=0.0)
    low: Series[float] = pa.Field(gt=0.0)
    close: Series[float] = pa.Field(gt=0.0)
    volume: Series[int] = pa.Field(ge=0)

    @pa.dataframe_check
    def high_ge_low(cls, df: pl.LazyFrame) -> pl.Expr:
        return pl.col("high") >= pl.col("low")

    @pa.dataframe_check
    def close_within_bars(cls, df: pl.LazyFrame) -> pl.Expr:
        return (pl.col("close") >= pl.col("low")) & (pl.col("close") <= pl.col("high"))

    class Config:
        strict = True
        coerce = True


class FundamentalsSchema(_ProvenanceMixin):
    """Quarterly financial results."""

    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    quarter_end: Series[str]
    revenue: Series[float]
    pat: Series[float]
    eps: Series[float]


class ShareholdingSchema(_ProvenanceMixin):
    """Quarterly shareholding pattern."""

    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    quarter_end: Series[str]
    promoter_pct: Series[float] = pa.Field(ge=0.0, le=100.0)
    fii_pct: Series[float] = pa.Field(ge=0.0, le=100.0)
    dii_pct: Series[float] = pa.Field(ge=0.0, le=100.0)
    public_pct: Series[float] = pa.Field(ge=0.0, le=100.0)


class DerivativesSchema(_ProvenanceMixin):
    """F&O daily data."""

    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    date: Series[str]
    instrument: Series[str]
    expiry: Series[str]
    strike: Series[float] = pa.Field(ge=0.0)
    option_type: Series[str]
    open_interest: Series[int] = pa.Field(ge=0)
    volume: Series[int] = pa.Field(ge=0)
    close: Series[float]


class IndexMembershipSchema(_ProvenanceMixin):
    """Historical index constituency with validity dates."""

    isin: Series[str] = pa.Field(str_length={"min_value": 12, "max_value": 12})
    index_name: Series[str]
    valid_from: Series[str]
    valid_to: Series[str]


class InstitutionalFlowSchema(_ProvenanceMixin):
    """Daily FII/DII buy/sell aggregates."""

    date: Series[str]
    category: Series[str]
    buy_value: Series[float]
    sell_value: Series[float]
    net_value: Series[float]


class DataQualitySchema(pa.DataFrameModel):
    """Per-source per-run data quality metrics."""

    source: Series[str]
    run_id: Series[str]
    run_date: Series[str]
    target_date: Series[str]
    row_count: Series[int] = pa.Field(ge=0)
    null_counts_json: Series[str]
    validation_failures: Series[int] = pa.Field(ge=0)
    date_gaps_json: Series[str]
    ingested_at: Series[str]
