from datetime import date
from typing import Any

import polars as pl

from indiquant.store.lakehouse import Lakehouse
from indiquant.store.pit import as_known_on


def _write_mock_fundamentals(lakehouse: Lakehouse, rows: list[dict[str, Any]]) -> None:
    if not rows:
        df = pl.DataFrame({"isin": [], "knowledge_date": [], "revenue": [], "year": []})
    else:
        df = pl.DataFrame(rows)
        if "year" not in df.columns:
            df = df.with_columns(pl.lit(2024).alias("year"))
    lakehouse.write_silver("fundamentals", df, year=2024)


def test_future_knowledge_date_invisible(tmp_lakehouse: Lakehouse) -> None:
    """A fundamental filed on 2024-05-28 must NOT appear when asof=2024-04-15."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE002A01018",
                "knowledge_date": "2024-05-28",
                "revenue": 1000.0,
            }
        ],
    )
    result = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 4, 15))
    assert result.empty


def test_past_knowledge_date_visible(tmp_lakehouse: Lakehouse) -> None:
    """A fundamental filed on 2024-05-28 must appear when asof=2024-06-01."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE002A01018",
                "knowledge_date": "2024-05-28",
                "revenue": 1000.0,
            }
        ],
    )
    result = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 6, 1))
    assert len(result) == 1
    assert result.iloc[0]["revenue"] == 1000.0


def test_latest_row_wins(tmp_lakehouse: Lakehouse) -> None:
    """When two filings exist for the same ISIN, return the latest <= asof."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE002A01018",
                "knowledge_date": "2024-03-15",
                "revenue": 800.0,
            },
            {
                "isin": "INE002A01018",
                "knowledge_date": "2024-05-28",
                "revenue": 1000.0,
            },
        ],
    )
    # Before the second filing
    res1 = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 4, 1))
    assert len(res1) == 1
    assert res1.iloc[0]["revenue"] == 800.0

    # After the second filing
    res2 = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 6, 1))
    assert len(res2) == 1
    assert res2.iloc[0]["revenue"] == 1000.0


def test_multiple_isins(tmp_lakehouse: Lakehouse) -> None:
    """Returns one row per ISIN when isin=None."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE001",
                "knowledge_date": "2024-01-01",
                "revenue": 10.0,
            },
            {
                "isin": "INE002",
                "knowledge_date": "2024-01-01",
                "revenue": 20.0,
            },
        ],
    )
    result = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 2, 1))
    assert len(result) == 2
    assert set(result["isin"]) == {"INE001", "INE002"}


def test_isin_filter(tmp_lakehouse: Lakehouse) -> None:
    """Returns only requested ISIN."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE001",
                "knowledge_date": "2024-01-01",
                "revenue": 10.0,
            },
            {
                "isin": "INE002",
                "knowledge_date": "2024-01-01",
                "revenue": 20.0,
            },
        ],
    )
    result = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 2, 1), isin="INE002")
    assert len(result) == 1
    assert result.iloc[0]["isin"] == "INE002"


def test_empty_table(tmp_lakehouse: Lakehouse) -> None:
    """Returns empty DataFrame gracefully on empty table."""
    result = as_known_on(tmp_lakehouse, table="missing_table", asof=date(2024, 1, 1))
    assert result.empty

    _write_mock_fundamentals(tmp_lakehouse, [])
    result = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 1, 1))
    assert result.empty


def test_point_event_boundary(tmp_lakehouse: Lakehouse) -> None:
    """A fundamental row with knowledge_date = 2024-05-30 must be returned for asof = 2024-05-30
    and NOT returned for asof = 2024-05-29."""
    _write_mock_fundamentals(
        tmp_lakehouse,
        [
            {
                "isin": "INE002A01018",
                "knowledge_date": "2024-05-30",
                "revenue": 1000.0,
            }
        ],
    )
    # The day before: should not be returned
    res_before = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 5, 29))
    assert res_before.empty

    # The exact day: should be returned
    res_on = as_known_on(tmp_lakehouse, table="fundamentals", asof=date(2024, 5, 30))
    assert len(res_on) == 1
    assert res_on.iloc[0]["revenue"] == 1000.0


def _write_mock_membership(lakehouse: Lakehouse, rows: list[dict[str, Any]]) -> None:
    if not rows:
        df = pl.DataFrame(
            {"index_name": [], "isin": [], "valid_from": [], "valid_to": [], "year": []}
        )
    else:
        df = pl.DataFrame(rows)
        if "year" not in df.columns:
            df = df.with_columns(pl.lit(2024).alias("year"))
    lakehouse.write_silver("index_membership", df, year=2024)


def test_interval_boundary(tmp_lakehouse: Lakehouse) -> None:
    """A membership row with valid_to = 2024-04-01 must NOT be returned for
    asof = 2024-04-01 (exclusive end)."""
    from indiquant.store.pit import index_constituents

    _write_mock_membership(
        tmp_lakehouse,
        [
            {
                "index_name": "NIFTY 50",
                "isin": "INE123",
                "valid_from": "2024-01-01",
                "valid_to": "2024-04-01",
            }
        ],
    )

    # Valid on day before (2024-03-31)
    assert "INE123" in index_constituents(tmp_lakehouse, "NIFTY 50", date(2024, 3, 31))

    # NOT valid on end date (2024-04-01)
    assert "INE123" not in index_constituents(tmp_lakehouse, "NIFTY 50", date(2024, 4, 1))


def test_delisting_eve_integration(tmp_lakehouse: Lakehouse) -> None:
    """Build constituents the day before a known historical delisting and
    assert the ISIN is still present."""
    from indiquant.store.pit import index_constituents

    # Pretend INE_DEAD was delisted on 2024-10-15 and removed from index.
    # It means its valid_to is 2024-10-15.
    _write_mock_membership(
        tmp_lakehouse,
        [
            {
                "index_name": "NIFTY 50",
                "isin": "INE_DEAD",
                "valid_from": "2020-01-01",
                "valid_to": "2024-10-15",
            }
        ],
    )

    # Eve of delisting: 2024-10-14 -> should be present
    eve = date(2024, 10, 14)
    constituents = index_constituents(tmp_lakehouse, "NIFTY 50", eve)
    assert "INE_DEAD" in constituents, (
        "Survivorship bias detected! Delisted ISIN missing on delisting eve."
    )
