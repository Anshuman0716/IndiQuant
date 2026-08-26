# AGENTS.md — Bharat Quant Lab

## What this project is
A point-in-time correct, survivorship-free systematic research and backtesting
platform for Indian equities (NSE/BSE). It ingests OHLCV, fundamentals,
derivatives and institutional flow data into a DuckDB/Parquet lakehouse,
computes a factor library, backtests strategies with the full Indian statutory
cost stack, validates results through an anti-overfitting harness, and ships
the whole thing as a FastAPI service plus an MCP server.

This is a portfolio project targeting a Quant Developer role at Tapetide, an
AI-first Indian stock research platform. The code must therefore be readable
by a hiring engineer, not just functional.

## Non-negotiable correctness rules
These are the rules the entire project exists to demonstrate. Violating any of
them silently invalidates every result the system produces.

1. POINT-IN-TIME. Fundamentals and shareholding data must NEVER be used before
   its `knowledge_date`. All such access goes through `store.pit.as_known_on()`.
   There are no exceptions. If you need fundamental data and that function does
   not support your case, extend the function — do not bypass it.

2. NO SURVIVORSHIP BIAS. Universes are constructed from historical index
   membership as of the rebalance date, including companies since delisted.
   Never filter on "currently listed".

3. ISIN IS THE PRIMARY KEY. Ticker symbols get renamed and reused. Every join
   is on ISIN. Symbol is a display attribute resolved through a validity-dated
   mapping table.

4. COSTS ARE DATE-EFFECTIVE. Indian statutory rates change with each Union
   Budget (F&O STT changed on 2026-04-01). The cost module is a lookup table
   keyed by (component, effective_from, effective_to), never a constant.

5. EVERY BACKTEST IS LOGGED. Every run, including exploratory ones, writes to
   the trial registry. The deflated Sharpe ratio depends on an honest trial
   count.

6. NO LOOKAHEAD IN SIGNALS. A signal computed for date T may only use data
   available at the close of T. Forward returns are labels, never features.

## Tech stack (do not substitute without asking)
- Python 3.12, pandas 2.x, NumPy, Polars (ingest only), uv for packaging
- DuckDB over partitioned Parquet for time-series; Postgres for metadata only
- vectorbt for cross-sectional backtests; a custom event loop for
  path-dependent constraints
- FastAPI + Pydantic v2 for the REST layer
- TypeScript + @modelcontextprotocol/sdk for the MCP server
- Docker, GitHub Actions, Google Cloud Run
- Sentry for errors, PostHog for analytics, structlog for logging

## Code standards
- Full type hints. `mypy --strict` passes on `src/`.
- ruff for lint and format. No suppressions without an inline reason comment.
- Docstrings on every public function: what it does, units, and any assumption
  that could silently be wrong.
- Financial functions state their units in the docstring (bps vs %, ₹ vs ₹ lakh).
- No magic numbers. Rates, thresholds and windows live in config or constants
  with a source comment (e.g. `# NSE circular 2026-03-28`).
- Tests: pytest. Every factor and every cost component has a test with a
  hand-computed expected value.
- No notebook code in `src/`. Notebooks import from `src/`, never the reverse.

## Things that are wrong here even though they are normal elsewhere
- `commission=0.001` as a cost model. India has seven separate charges plus a
  FLAT per-scrip DP fee. Model them individually.
- Standard K-fold cross-validation. Financial labels overlap; use purged CV
  with an embargo.
- Filling an order at any size. Cap fills at a percentage of ADV and carry the
  residual forward.
- `yfinance` as a production source. Acceptable for a smoke test only, and it
  must be clearly marked as such.
- Dropping NaNs silently. State a missing-data policy per factor and log how
  many rows it affected.

## Working style
- Produce an implementation plan before writing code on any task touching more
  than two files. Wait for approval.
- Prefer small, composable modules over large orchestrators.
- When a design decision has real trade-offs, write an ADR in `docs/adr/`.
- If a requirement is ambiguous, ask. Do not guess and proceed.
- After implementing, run the tests yourself and show the output. Do not claim
  success without evidence.
