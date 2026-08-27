from datetime import date

import duckdb
import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


def as_known_on(
    lakehouse: Lakehouse,
    table: str,
    asof: date,
    isin: str | None = None,
) -> pd.DataFrame:
    """Return the latest row per ISIN where knowledge_date <= asof.

    This function enforces AGENTS.md Rule #1 (POINT-IN-TIME). It is the
    ONLY sanctioned way to access fundamental, shareholding, or any
    knowledge-date-gated data.

    The query:
        1. Filters to rows where knowledge_date <= asof
        2. Partitions by ISIN
        3. Ranks by knowledge_date DESC within each ISIN
        4. Returns only rank-1 rows (the most recent known data)

    Args:
        lakehouse: Lakehouse instance.
        table: Silver table name (e.g. "fundamentals").
        asof: The point-in-time date. Only data known on or before this
              date is visible.
        isin: Optional ISIN filter. If None, returns all ISINs.

    Returns:
        pandas DataFrame with the latest known row per ISIN.
    """
    logger.debug(
        "executing_pit_query",
        table=table,
        asof=asof.isoformat(),
        isin=isin,
    )

    table_path = (lakehouse.silver_dir / table / "**/*.parquet").as_posix()

    # We use union_by_name=true to handle schema evolution cleanly
    query = f"""
    WITH ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY isin
                ORDER BY knowledge_date DESC
            ) AS _rn
        FROM read_parquet(
            '{table_path}',
            hive_partitioning = true,
            union_by_name = true
        )
        WHERE knowledge_date <= $asof
          AND ($isin IS NULL OR isin = $isin)
    )
    SELECT * EXCLUDE (_rn)
    FROM ranked
    WHERE _rn = 1
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query, {"asof": asof.isoformat(), "isin": isin}).df()
    except duckdb.IOException:
        logger.warning(
            "pit_query_no_files",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
        )
        return pd.DataFrame()

    if df.empty:
        logger.warning(
            "pit_query_empty",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
            msg="Table may legitimately have no data for this ISIN/date.",
        )
    else:
        logger.debug(
            "pit_query_complete",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
            rows=len(df),
        )

    return df
