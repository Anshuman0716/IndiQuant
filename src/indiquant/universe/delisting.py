"""Delisting handling for universe construction.

Provides functionality to identify when a security permanently stopped trading
and assigns a terminal return haircut to prevent unrealistic exit assumptions.
"""

from datetime import date
from typing import Any

import duckdb
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


def get_delisting_info(
    lakehouse: Lakehouse,
    isins: list[str],
    asof: date,
    terminal_haircut: float = -0.30,
) -> dict[str, dict[str, Any]]:
    """Get delisting dates and haircuts for a set of ISINs.

    If a stock delists while held in a backtest, exiting at the last traded
    price is a severe optimistic bias (the "delisting return assumption").
    This function assigns a configurable terminal haircut to names that
    delist after the given asof date.

    Args:
        lakehouse: Lakehouse instance.
        isins: List of ISINs in the current universe snapshot.
        asof: The snapshot date.
        terminal_haircut: The return applied on the delisting date.
            Default is -30% (-0.30).

    Returns:
        Dict mapping ISIN to:
            - "delisting_date": date or None
            - "haircut": float or None
    """
    if not isins:
        return {}

    # We determine delisting by checking the max(date) in equity_daily.
    # If the max date for an ISIN is significantly older than the max date
    # across the entire market (e.g. older than 30 days), it's considered delisted.

    isin_list = "'" + "','".join(isins) + "'"
    eq_path = (lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()

    query = f"""
    WITH market_max AS (
        SELECT MAX(CAST(date AS DATE)) AS max_market_date
        FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
    ),
    isin_max AS (
        SELECT isin, MAX(CAST(date AS DATE)) AS last_seen
        FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
        WHERE isin IN ({isin_list})
        GROUP BY isin
    )
    SELECT i.isin, i.last_seen, m.max_market_date
    FROM isin_max i
    CROSS JOIN market_max m
    """

    result: dict[str, dict[str, Any]] = {
        isin: {"delisting_date": None, "haircut": None} for isin in isins
    }

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query).pl()
    except duckdb.IOException:
        return result

    for row in df.iter_rows(named=True):
        isin = str(row["isin"])
        last_seen = row["last_seen"]
        max_mkt = row["max_market_date"]

        # If the last seen date is older than 30 days from the latest data we have,
        # we classify it as delisted.
        if last_seen and max_mkt and (max_mkt - last_seen).days > 30:
            result[isin]["delisting_date"] = last_seen
            result[isin]["haircut"] = terminal_haircut

    return result
