# 0001: DuckDB over Postgres for Time-Series

## Context
Market data ingestion (OHLCV, factors, etc.) is append-heavy, columnar-scan-heavy, and partitioned by date. Postgres with TimescaleDB incurs significant operational overhead for a single-user research platform.

## Decision
DuckDB over partitioned Parquet files will be used for all time-series data. Postgres will be used for metadata and the trial registry.

## Alternatives Rejected
1. **Postgres with TimescaleDB**: Too much operational overhead.
2. **SQLite**: Lacks columnar scans and Parquet integration.
3. **ClickHouse**: Overkill, requires a running server.

## Consequences
No multi-writer concurrency on time-series (acceptable for single-researcher workflows). Parquet files are portable and can be shipped to cloud storage easily.
