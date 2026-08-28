"""Corporate action adjustments for historical price and volume data.

Applies cumulative adjustments backwards in time so that historical prices
are comparable to the end date of the requested range.
"""

from datetime import date
from typing import Any, Literal

import polars as pl
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


def adjusted_prices(
    lakehouse: Lakehouse,
    isins: list[str],
    start: date,
    end: date,
    adjust_for: list[Literal["split", "bonus", "dividend"]] | None = None,
) -> pl.DataFrame:
    """Get price and volume data adjusted for corporate actions.

    Adjustments are computed relative to the `end` date. A price on date T
    is multiplied by the cumulative product of all adjustment factors that
    went ex-date between T (exclusive) and end (inclusive).

    Args:
        lakehouse: Lakehouse instance.
        isins: List of ISINs.
        start: Start date.
        end: End date.
        adjust_for: Types of corporate actions to adjust for. Defaults to
            ["split", "bonus", "dividend"].

    Returns:
        DataFrame with adjusted OHLCV. Columns:
        isin, date, open, high, low, close, volume,
        adj_open, adj_high, adj_low, adj_close, adj_volume
    """
    if adjust_for is None:
        adjust_for = ["split", "bonus", "dividend"]

    if not isins:
        return pl.DataFrame()

    # 1. Fetch raw daily prices
    eq_path = (lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
    isin_list = "'" + "','".join(isins) + "'"

    query = f"""
    SELECT isin, date, open, high, low, close, volume
    FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
    WHERE isin IN ({isin_list})
      AND date >= '{start.isoformat()}'
      AND date <= '{end.isoformat()}'
    """
    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query).pl()
    except Exception:
        return pl.DataFrame()

    if len(df) == 0:
        return df

    # 2. Fetch corporate actions
    ca_path = (lakehouse.silver_dir / "corporate_actions" / "**/*.parquet").as_posix()
    ca_query = f"""
    SELECT isin, ex_date, action_type, ratio_from, ratio_to, amount_per_share
    FROM read_parquet('{ca_path}', hive_partitioning = true, union_by_name = true)
    WHERE isin IN ({isin_list})
      AND ex_date > '{start.isoformat()}'
      AND ex_date <= '{end.isoformat()}'
    """
    try:
        with lakehouse.connection() as cur:
            ca_df = cur.execute(ca_query).pl()
    except Exception:
        ca_df = pl.DataFrame(
            schema={
                "isin": pl.Utf8,
                "ex_date": pl.Utf8,
                "action_type": pl.Utf8,
                "ratio_from": pl.Float64,
                "ratio_to": pl.Float64,
                "amount_per_share": pl.Float64,
            }
        )

    if len(ca_df) == 0 or not adjust_for:
        return _add_unadjusted_columns(df)

    ca_df = ca_df.filter(pl.col("action_type").is_in(adjust_for))
    if len(ca_df) == 0:
        return _add_unadjusted_columns(df)

    # 3. Compute adjustment multipliers for each ex-date
    df_sorted = df.sort(["isin", "date"])

    # Get prev_close for each date
    df_prev = df_sorted.with_columns(pl.col("close").shift(1).over("isin").alias("prev_close"))

    ca_joined = ca_df.join(
        df_prev.select(["isin", "date", "prev_close"]),
        left_on=["isin", "ex_date"],
        right_on=["isin", "date"],
        how="left",
    )

    multipliers: list[dict[str, Any]] = []
    for row in ca_joined.to_dicts():
        multipliers.append(
            {
                "isin": row["isin"],
                "date": row["ex_date"],
                "p_mult": _calc_price_mult(row),
                "v_mult": _calc_vol_mult(row),
            }
        )

    mult_df = pl.DataFrame(multipliers)

    # Aggregate multiple CA on the same day (e.g. split + dividend)
    mult_df = mult_df.group_by(["isin", "date"]).agg(
        pl.col("p_mult").product(), pl.col("v_mult").product()
    )

    df_adj = df_sorted.join(mult_df, on=["isin", "date"], how="left")
    df_adj = df_adj.with_columns(
        [
            pl.col("p_mult").fill_null(1.0),
            pl.col("v_mult").fill_null(1.0),
        ]
    )

    # 4. Cumulative product backwards
    # Reverse sort by date, compute cumprod, shift 1, then fill_null(1.0).
    df_adj = df_adj.sort(["isin", "date"], descending=[False, True])

    df_adj = df_adj.with_columns(
        [
            pl.col("p_mult").cum_prod().over("isin").shift(1).fill_null(1.0).alias("p_cum"),
            pl.col("v_mult").cum_prod().over("isin").shift(1).fill_null(1.0).alias("v_cum"),
        ]
    )

    df_adj = df_adj.sort(["isin", "date"])

    df_adj = df_adj.with_columns(
        [
            (pl.col("open") * pl.col("p_cum")).alias("adj_open"),
            (pl.col("high") * pl.col("p_cum")).alias("adj_high"),
            (pl.col("low") * pl.col("p_cum")).alias("adj_low"),
            (pl.col("close") * pl.col("p_cum")).alias("adj_close"),
            (pl.col("volume") * pl.col("v_cum")).cast(pl.Int64).alias("adj_volume"),
        ]
    )

    return df_adj.select(
        [
            "isin",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adj_open",
            "adj_high",
            "adj_low",
            "adj_close",
            "adj_volume",
        ]
    )


def _add_unadjusted_columns(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        [
            pl.col("open").alias("adj_open"),
            pl.col("high").alias("adj_high"),
            pl.col("low").alias("adj_low"),
            pl.col("close").alias("adj_close"),
            pl.col("volume").alias("adj_volume"),
        ]
    ).sort(["isin", "date"])


def _calc_price_mult(row: dict[str, Any]) -> float:
    action = row["action_type"]
    if action == "split":
        return float(row["ratio_to"] / row["ratio_from"]) if row["ratio_from"] else 1.0
    elif action == "bonus":
        total = row["ratio_from"] + row["ratio_to"]
        return float(row["ratio_to"] / total) if total else 1.0
    elif action == "dividend":
        prev_close = row["prev_close"]
        div = row["amount_per_share"]
        if prev_close and prev_close > 0 and div:
            return float(max(0.0, (prev_close - div) / prev_close))
        return 1.0
    return 1.0


def _calc_vol_mult(row: dict[str, Any]) -> float:
    action = row["action_type"]
    if action == "split":
        return float(row["ratio_from"] / row["ratio_to"]) if row["ratio_to"] else 1.0
    elif action == "bonus":
        return (
            float((row["ratio_from"] + row["ratio_to"]) / row["ratio_to"])
            if row["ratio_to"]
            else 1.0
        )
    return 1.0
