"""Tests for the DuckDB Lakehouse storage layer."""

from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse


@pytest.fixture
def test_lakehouse(tmp_path: Path) -> Lakehouse:
    """Provide a Lakehouse instance pointing to a temporary directory."""
    settings = IndiQuantSettings()
    settings.data_dir = tmp_path / "data"
    return Lakehouse(settings)


def test_write_silver_appends_within_partition(test_lakehouse: Lakehouse) -> None:
    """Regression test: write_silver must append, not overwrite.

    Writing day N and then day N+1 to the same year partition must result in
    both days' rows being present, rather than day N being destroyed.
    """
    table_name = "test_equity"
    year = 2024

    # Day 1: 2024-01-01
    df1 = pl.DataFrame(
        {
            "isin": ["INE123"],
            "date": ["2024-01-01"],
            "close": [100.0],
            "year": [year],
        }
    )
    test_lakehouse.write_silver(table_name, df1, year=year)

    # Day 2: 2024-01-02
    df2 = pl.DataFrame(
        {
            "isin": ["INE456"],
            "date": ["2024-01-02"],
            "close": [105.0],
            "year": [year],
        }
    )
    test_lakehouse.write_silver(table_name, df2, year=year)

    # Read the full table back
    result_df = test_lakehouse.read_table(table_name)
    
    # Assert both days' rows are present
    assert len(result_df) == 2
    
    dates_present = set(result_df["date"].tolist())
    assert "2024-01-01" in dates_present, "Day N was silently overwritten!"
    assert "2024-01-02" in dates_present, "Day N+1 is missing!"

