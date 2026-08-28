"""Corporate action adjustments for historical price and volume data.

Applies cumulative adjustments backwards in time so that historical prices
are comparable to the end date of the requested range. Uses pandas.
"""

from datetime import date
from typing import Any, Literal

import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


def adjusted_prices(
    lakehouse: Lakehouse,
    isins: list[str],
    start: date,
    end: date,
    adjust_for: list[Literal["split", "bonus", "dividend"]] | None = None,
) -> pd.DataFrame:
    """Get price and volume data adjusted for corporate actions.

    Adjustments are computed relative to the `end` date. A price on date T
    is multiplied by the cumulative product of all adjustment factors that
    went ex-date between T (exclusive) and end (inclusive).
    
    Generates two series of adjustments:
    - Technical (split/bonus only) applied to open/high/low/close/volume.
    - Total Return (split/bonus/dividend) applied only to a separate 
      `adj_tot_close` column for benchmark tracking.

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
        adj_open, adj_high, adj_low, adj_close, adj_tot_close, adj_volume
    """
    if adjust_for is None:
        adjust_for = ["split", "bonus", "dividend"]

    if not isins:
        return pd.DataFrame()

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
            df = cur.execute(query).df()
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # Fetch corporate actions
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
            ca_df = cur.execute(ca_query).df()
    except Exception:
        ca_df = pd.DataFrame(columns=[
            "isin", "ex_date", "action_type", "ratio_from", "ratio_to", "amount_per_share"
        ])

    if ca_df.empty or not adjust_for:
        return _add_unadjusted_columns(df)

    ca_df = ca_df[ca_df["action_type"].isin(adjust_for)]
    if ca_df.empty:
        return _add_unadjusted_columns(df)

    df_sorted = df.sort_values(["isin", "date"]).reset_index(drop=True)
    
    # Get prev_close for each date
    df_sorted["prev_close"] = df_sorted.groupby("isin")["close"].shift(1)

    ca_joined = pd.merge(
        ca_df,
        df_sorted[["isin", "date", "prev_close"]],
        left_on=["isin", "ex_date"],
        right_on=["isin", "date"],
        how="left",
    )

    multipliers: list[dict[str, Any]] = []
    for _, row in ca_joined.iterrows():
        p_mult, div_mult = _calc_price_mults(row)
        multipliers.append(
            {
                "isin": row["isin"],
                "date": row["ex_date"],
                "tech_mult": p_mult,
                "tot_mult": p_mult * div_mult,
                "v_mult": _calc_vol_mult(row),
            }
        )

    mult_df = pd.DataFrame(multipliers)
    
    if not mult_df.empty:
        # Aggregate multiple CA on the same day
        mult_df = mult_df.groupby(["isin", "date"], as_index=False).prod()

    df_adj = pd.merge(df_sorted, mult_df, on=["isin", "date"], how="left")
    df_adj["tech_mult"] = df_adj["tech_mult"].fillna(1.0)
    df_adj["tot_mult"] = df_adj["tot_mult"].fillna(1.0)
    df_adj["v_mult"] = df_adj["v_mult"].fillna(1.0)

    # Cumulative product backwards
    # Reverse sort
    df_adj = df_adj.sort_values(["isin", "date"], ascending=[True, False]).reset_index(drop=True)
    
    df_adj["tech_cum"] = df_adj.groupby("isin")["tech_mult"].cumprod().shift(1).fillna(1.0)
    df_adj["tot_cum"] = df_adj.groupby("isin")["tot_mult"].cumprod().shift(1).fillna(1.0)
    df_adj["v_cum"] = df_adj.groupby("isin")["v_mult"].cumprod().shift(1).fillna(1.0)
    
    # Sort back to chronological
    df_adj = df_adj.sort_values(["isin", "date"]).reset_index(drop=True)

    df_adj["adj_open"] = df_adj["open"] * df_adj["tech_cum"]
    df_adj["adj_high"] = df_adj["high"] * df_adj["tech_cum"]
    df_adj["adj_low"] = df_adj["low"] * df_adj["tech_cum"]
    df_adj["adj_close"] = df_adj["close"] * df_adj["tech_cum"]
    df_adj["adj_tot_close"] = df_adj["close"] * df_adj["tot_cum"]
    df_adj["adj_volume"] = (df_adj["volume"] * df_adj["v_cum"]).astype("Int64")

    cols = [
        "isin", "date", "open", "high", "low", "close", "volume",
        "adj_open", "adj_high", "adj_low", "adj_close", "adj_tot_close", "adj_volume"
    ]
    return df_adj[cols]


def _add_unadjusted_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["adj_open"] = df["open"]
    df["adj_high"] = df["high"]
    df["adj_low"] = df["low"]
    df["adj_close"] = df["close"]
    df["adj_tot_close"] = df["close"]
    df["adj_volume"] = df["volume"].astype("Int64")
    return df.sort_values(["isin", "date"]).reset_index(drop=True)


def _calc_price_mults(row: pd.Series) -> tuple[float, float]:
    """Calculate (technical_multiplier, dividend_multiplier)."""
    action = row["action_type"]
    if action == "split":
        return float(row["ratio_to"] / row["ratio_from"]) if row["ratio_from"] else 1.0, 1.0
    elif action == "bonus":
        total = row["ratio_from"] + row["ratio_to"]
        return float(row["ratio_to"] / total) if total else 1.0, 1.0
    elif action == "dividend":
        prev_close = row["prev_close"]
        div = row["amount_per_share"]
        if pd.notnull(prev_close) and prev_close > 0 and pd.notnull(div):
            return 1.0, float(max(0.0, (prev_close - div) / prev_close))
        return 1.0, 1.0
    return 1.0, 1.0


def _calc_vol_mult(row: pd.Series) -> float:
    action = row["action_type"]
    if action == "split":
        return float(row["ratio_from"] / row["ratio_to"]) if row["ratio_to"] else 1.0
    elif action == "bonus":
        return float((row["ratio_from"] + row["ratio_to"]) / row["ratio_to"]) if row["ratio_to"] else 1.0
    return 1.0
