"""Index membership queries and universe construction helpers.

This module delegates directly to store.pit for historical queries to
ensure point-in-time correctness and survivorship-bias elimination.
"""

from datetime import date

from indiquant.store.lakehouse import Lakehouse
from indiquant.store.pit import index_constituents, is_index_member


def constituents(
    index: str,
    asof: date,
    lakehouse: Lakehouse,
) -> list[str]:
    """Get all ISINs constituting an index as of a specific date.

    Args:
        index: The index name (e.g., 'NIFTY 500').
        asof: The date to check membership for.
        lakehouse: Lakehouse instance.

    Returns:
        List of ISINs in the index on the given date.
    """
    return index_constituents(lakehouse, index, asof)


def is_member(
    isin: str,
    index: str,
    asof: date,
    lakehouse: Lakehouse,
) -> bool:
    """Check if an ISIN was a member of an index on a specific date.

    Args:
        isin: The ISIN to check.
        index: The index name (e.g., 'NIFTY 500').
        asof: The date to check membership for.
        lakehouse: Lakehouse instance.

    Returns:
        True if the ISIN was a constituent on that date.
    """
    return is_index_member(lakehouse, isin, index, asof)
