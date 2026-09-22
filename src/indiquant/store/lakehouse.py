from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import polars as pl

from indiquant.config.settings import IndiQuantSettings


class Lakehouse:
    """DuckDB-backed lakehouse over Hive-partitioned Parquet files.

    Bronze layer: data/bronze/{source}/{table}/year={Y}/month={M}/
    Silver layer: data/silver/{table}/year={Y}/
    Meta layer:   data/meta/{table}/year={Y}/
    """

    def __init__(self, settings: IndiQuantSettings) -> None:
        """Initialise connection manager."""
        self.data_dir = settings.data_dir
        self.bronze_dir = self.data_dir / "bronze"
        self.silver_dir = self.data_dir / "silver"
        self.meta_dir = self.data_dir / "meta"

        # We use an in-memory database instance to query the parquet files.
        # This gives us lock-free compute while data rests on disk.
        self._con = duckdb.connect()
        self._con.execute("SET preserve_insertion_order = false;")
        self._con.execute("SET partitioned_write_max_open_files = 100;")

    @contextmanager
    def connection(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Yield a thread-local cursor."""
        cursor = self._con.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def bronze_exists(self, source: str, table: str, target_date: date) -> bool:
        """Check whether bronze partition already exists for this date."""
        path = (
            self.bronze_dir
            / source
            / table
            / f"year={target_date.year}"
            / f"month={target_date.month}"
            / f"{target_date.isoformat()}.parquet"
        )
        return path.exists()

    def write_bronze(
        self,
        source: str,
        table: str,
        df: pl.DataFrame,
        target_date: date,
        force: bool = False,
    ) -> Path:
        """Write a Polars DataFrame to bronze Parquet. Immutable."""
        path = (
            self.bronze_dir
            / source
            / table
            / f"year={target_date.year}"
            / f"month={target_date.month}"
            / f"{target_date.isoformat()}.parquet"
        )
        if not force and path.exists():
            raise FileExistsError(f"Bronze file already exists: {path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path, compression="zstd")
        return path

    def write_silver(self, table: str, df: pl.DataFrame, year: int) -> Path:
        """Write to silver Parquet, partitioned by year.

        Appends a new file atomically to the partition directory.
        """
        table_dir = self.silver_dir / table
        partition_dir = table_dir / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        import tempfile
        import shutil
        import os

        # We don't need the 'year' column in the parquet file itself for hive partitioning
        if "year" in df.columns:
            df = df.drop("year")

        tmp_dir = Path(tempfile.mkdtemp(prefix="indiquant_write_"))
        file_id = uuid.uuid4().hex[:8]
        tmp_file = tmp_dir / f"data_{file_id}.parquet"

        try:
            # Write to temp file
            df.write_parquet(tmp_file, compression="zstd")
            
            # Atomically move into partition directory
            target_file = partition_dir / tmp_file.name
            os.rename(tmp_file, target_file)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            
        return table_dir

    def read_table(
        self,
        name: str,
        start: date | None = None,
        end: date | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Read from silver layer with predicate pushdown. Returns pandas."""
        table_path = (self.silver_dir / name / "**/*.parquet").as_posix()

        query = f"SELECT * FROM read_parquet('{table_path}', hive_partitioning = true, union_by_name = true)"  # noqa: E501

        where_clauses: list[str] = []
        params: list[Any] = []

        if start:
            where_clauses.append("date >= ?")
            params.append(start.isoformat())
        if end:
            where_clauses.append("date <= ?")
            params.append(end.isoformat())

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        if columns:
            col_str = ", ".join(columns)
            query = query.replace("SELECT *", f"SELECT {col_str}")

        with self.connection() as cur:
            return cur.execute(query, params).df()

    def write_quality_log(self, record: dict[str, Any]) -> None:
        """Append a data-quality record to the meta layer."""
        # Convert record to single-row dataframe
        df = pl.DataFrame([record])
        target_date = date.fromisoformat(record["target_date"])
        year = target_date.year
        df = df.with_columns(pl.lit(year).alias("year"))

        log_dir = self.meta_dir / "data_quality"
        log_dir.mkdir(parents=True, exist_ok=True)

        # We append to the existing partition file using DuckDB,
        # or create it if it doesn't exist.
        with self.connection() as cur:
            cur.execute(
                f"""
                COPY (SELECT * FROM df)
                TO '{log_dir.as_posix()}' (
                    FORMAT PARQUET,
                    PARTITION_BY (year),
                    APPEND 1,
                    COMPRESSION ZSTD
                );
                """
            )

    def read_quality_log(self, source: str | None = None) -> pd.DataFrame:
        """Read data-quality records."""
        log_dir = (self.meta_dir / "data_quality" / "**/*.parquet").as_posix()
        query = f"SELECT * FROM read_parquet('{log_dir}', hive_partitioning = true, union_by_name = true)"  # noqa: E501
        params: list[str] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)

        with self.connection() as cur:
            try:
                return cur.execute(query, params).df()
            except duckdb.IOException:
                # Table does not exist yet
                return pd.DataFrame()
