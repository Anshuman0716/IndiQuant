"""Liquidity filters for universe construction.

Computes rolling metrics like 60-day median turnover and enforces gates
for price, listing days, and minimum turnover to avoid microcap anomalies.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb
import polars as pl
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


@dataclass
class LiquidityResult:
    """Result of liquidity screening."""

    passed: list[str]
    rejected: dict[str, str]  # ISIN -> Reason for rejection


def screen_liquidity(
    lakehouse: Lakehouse,
    isins: list[str],
    asof: date,
    min_price: float = 10.0,
    min_turnover: float = 1_000_000.0,
    min_listing_days: int = 60,
    window: int = 60,
) -> LiquidityResult:
    """Apply liquidity gates as of a specific date.

    Args:
        lakehouse: Lakehouse instance.
        isins: Initial universe of ISINs to screen.
        asof: Point-in-time date for the screen.
        min_price: Minimum median close price in the window (default Rs 10).
        min_turnover: Minimum median daily turnover in the window.
        min_listing_days: Minimum number of traded days required in the window.
        window: Lookback window in trading days.

    Returns:
        LiquidityResult with passed ISINs and rejection reasons.
    """
    if not isins:
        return LiquidityResult(passed=[], rejected={})

    # We need at least `window` trading days. A safe calendar buffer is ~1.5x.
    start_date = asof - timedelta(days=int(window * 1.5) + 30)

    isin_list = "'" + "','".join(isins) + "'"
    eq_path = (lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()

    # Query the last `window` rows per ISIN up to `asof`.
    query = f"""
    WITH ranked AS (
        SELECT isin, date, close, volume,
               (close * volume) AS turnover,
               ROW_NUMBER() OVER (
                   PARTITION BY isin 
                   ORDER BY date DESC
               ) AS _rn
        FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
        WHERE isin IN ({isin_list})
          AND date <= '{asof.isoformat()}'
          AND date >= '{start_date.isoformat()}'
    )
    SELECT * EXCLUDE(_rn)
    FROM ranked
    WHERE _rn <= {window}
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query).pl()
    except duckdb.IOException:
        # Table missing
        return LiquidityResult(passed=[], rejected={i: "no_data" for i in isins})

    if len(df) == 0:
        return LiquidityResult(passed=[], rejected={i: "no_data" for i in isins})

    # Compute aggregates per ISIN
    agg = df.group_by("isin").agg(
        [
            pl.len().alias("listing_days"),
            pl.col("close").median().alias("median_price"),
            pl.col("turnover").median().alias("median_turnover"),
        ]
    )

    passed = []
    rejected = {}

    # We must also account for ISINs that had zero rows returned
    found_isins = set(agg["isin"].to_list())
    for isin in isins:
        if isin not in found_isins:
            rejected[isin] = "no_data"

    for row in agg.iter_rows(named=True):
        isin = str(row["isin"])
        days = int(row["listing_days"])
        price = float(row["median_price"])
        turnover = float(row["median_turnover"])

        if days < min_listing_days:
            rejected[isin] = f"listing_days_too_low ({days} < {min_listing_days})"
        elif price < min_price:
            rejected[isin] = f"price_too_low ({price:.2f} < {min_price})"
        elif turnover < min_turnover:
            rejected[isin] = f"turnover_too_low ({turnover:.2f} < {min_turnover})"
        else:
            passed.append(isin)

    return LiquidityResult(passed=passed, rejected=rejected)
