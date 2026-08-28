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


def index_constituents(
    lakehouse: Lakehouse,
    index_name: str,
    asof: date,
) -> list[str]:
    """Return the ISINs constituting an index on a specific date.

    Enforces interval point-in-time constraints.
    Interval bounds: valid_from <= asof < valid_to.

    Args:
        lakehouse: Lakehouse instance.
        index_name: Index name (e.g. 'NIFTY 500').
        asof: The point-in-time date.

    Returns:
        List of ISINs.
    """
    logger.debug(
        "executing_index_constituents_query",
        index=index_name,
        asof=asof.isoformat(),
    )

    table_path = (lakehouse.silver_dir / "index_membership" / "**/*.parquet").as_posix()

    query = f"""
    SELECT isin
    FROM read_parquet(
        '{table_path}',
        hive_partitioning = true,
        union_by_name = true
    )
    WHERE index_name = $index
      AND valid_from <= $asof
      AND (valid_to IS NULL OR valid_to > $asof)
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query, {"index": index_name, "asof": asof.isoformat()}).df()
            return df["isin"].tolist()
    except duckdb.IOException:
        return []


def is_index_member(
    lakehouse: Lakehouse,
    isin: str,
    index_name: str,
    asof: date,
) -> bool:
    """Check if an ISIN was part of an index on a specific date.

    Args:
        lakehouse: Lakehouse instance.
        isin: The ISIN to check.
        index_name: Index name.
        asof: The point-in-time date.

    Returns:
        True if the ISIN was a member on the given date, False otherwise.
    """
    table_path = (lakehouse.silver_dir / "index_membership" / "**/*.parquet").as_posix()

    query = f"""
    SELECT 1
    FROM read_parquet(
        '{table_path}',
        hive_partitioning = true,
        union_by_name = true
    )
    WHERE index_name = $index
      AND isin = $isin
      AND valid_from <= $asof
      AND (valid_to IS NULL OR valid_to > $asof)
    LIMIT 1
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(
                query, {"index": index_name, "isin": isin, "asof": asof.isoformat()}
            ).df()
            return not df.empty
    except duckdb.IOException:
        return False
