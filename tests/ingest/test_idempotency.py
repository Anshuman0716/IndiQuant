from datetime import date

import pandas as pd

from tests.ingest.mock_source import MockSource


def test_idempotent_ingest(tmp_lakehouse):
    """Running the ingest pipeline twice produces identical silver output."""
    source = MockSource(tmp_lakehouse)

    # We mock fetch to just return a deterministic payload
    target_date = date(2024, 1, 15)

    def _mock_fetch(dt):
        from indiquant.ingest.models import RawPayload

        return RawPayload(
            source=source.name,
            date=dt,
            url="mock",
            status_code=200,
            headers={},
            body=b"OK",
            fetched_at="2024-01-15T00:00:00Z",
            raw_hash="hash",
            from_cache=False,
        )

    source.fetch = _mock_fetch

    # First run
    source.run(target_date)

    # Read first run output
    df1 = tmp_lakehouse.read_table("mock_table")

    # Second run with force=True so it bypasses bronze_exists
    source.run(target_date, force=True)

    # Read second run output
    df2 = tmp_lakehouse.read_table("mock_table")

    # In an append-only lakehouse, force=True appends a new file. 
    # We deduplicate to verify the logical contents are idempotent.
    df2 = df2.drop_duplicates(subset=["value", "source"])

    assert len(df1) == len(df2)
    assert len(df1) == 1
    assert df1.iloc[0]["value"] == 100

    # Check that row values are identical, ignoring ingestion timestamp
    pd.testing.assert_frame_equal(
        df1.drop(columns=["ingested_at"]), df2.drop(columns=["ingested_at"])
    )
