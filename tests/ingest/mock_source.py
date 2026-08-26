import pandera.polars as pa
import polars as pl
from datetime import date
from pandera.typing.polars import Series

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

class MockSchema(pa.DataFrameModel):
    value: Series[int] = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True


class MockSource(Source):
    name = "mock_source"
    schema = MockSchema
    silver_table = "mock_table"

    def _build_url(self, target_date: date) -> str:
        return f"http://mock.local/{target_date.isoformat()}"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        if b"INVALID" in raw.body:
            return pl.DataFrame({"value": [-1]})
        return pl.DataFrame({"value": [100]})

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        return bronze
