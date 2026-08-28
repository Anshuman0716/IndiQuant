"""Delisting handling for universe construction.

Provides functionality to identify when a security permanently stopped trading
and assigns a terminal return haircut to prevent unrealistic exit assumptions.
Uses explicit delisting datasets rather than dangerous absence heuristics.
"""

from datetime import date
from typing import Any

import duckdb
import pandas as pd
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

    Args:
        lakehouse: Lakehouse instance.
        isins: List of ISINs in the current universe snapshot.
        asof: The snapshot date.
        terminal_haircut: Default penalty applied on unknown/compulsory delisting.

    Returns:
        Dict mapping ISIN to:
            - "delisting_date": date or None
            - "haircut": float or None
            - "delisting_reason": Literal["compulsory", "voluntary_exit", "merger_acquisition", "unknown"]
    """
    if not isins:
        return {}

    isin_list = "'" + "','".join(isins) + "'"
    
    result: dict[str, dict[str, Any]] = {
        isin: {
            "delisting_date": None,
            "haircut": None,
            "delisting_reason": "unknown",
        } 
        for isin in isins
    }

    # 1. Check actual delisting source (to be built in Phase 1b/2b)
    # The source nse_delisting will land in `delistings` silver table.
    delist_path = (lakehouse.silver_dir / "delistings" / "**/*.parquet").as_posix()
    
    try:
        with lakehouse.connection() as cur:
            df_delist = cur.execute(f"""
                SELECT isin, delisting_date, reason
                FROM read_parquet('{delist_path}', hive_partitioning = true, union_by_name = true)
                WHERE isin IN ({isin_list})
                  AND delisting_date > '{asof.isoformat()}'
            """).df()
            
            for _, row in df_delist.iterrows():
                isin = str(row["isin"])
                d_date = row["delisting_date"]
                reason = str(row["reason"])
                
                result[isin]["delisting_date"] = d_date
                result[isin]["delisting_reason"] = reason
                
                if reason == "merger_acquisition":
                    # M&A usually exits at fair value or premium, no arbitrary penalty
                    result[isin]["haircut"] = 0.0
                else:
                    result[isin]["haircut"] = terminal_haircut
                    
    except duckdb.IOException:
        # Table doesn't exist yet, which is expected before the source is built.
        pass

    # 2. Heuristic check: warn only, do NOT silently apply haircut
    eq_path = (lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
    
    query_heuristic = f"""
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
    
    try:
        with lakehouse.connection() as cur:
            df_heur = cur.execute(query_heuristic).df()
            
        for _, row in df_heur.iterrows():
            isin = str(row["isin"])
            last_seen = row["last_seen"]
            max_mkt = row["max_market_date"]
            
            if pd.notnull(last_seen) and pd.notnull(max_mkt):
                # Using 30 days logic for WARNING only
                if (max_mkt - last_seen).days > 30:
                    if result[isin]["delisting_date"] is None:
                        logger.warning(
                            "potential_silent_delisting",
                            isin=isin,
                            last_seen=last_seen.isoformat() if hasattr(last_seen, "isoformat") else str(last_seen),
                            max_mkt=max_mkt.isoformat() if hasattr(max_mkt, "isoformat") else str(max_mkt),
                            msg="ISIN is missing from recent equity_daily files but has no explicit delisting record. Manual review required."
                        )
    except duckdb.IOException:
        pass

    return result
