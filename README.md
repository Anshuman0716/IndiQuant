# IndiQuant

A **point-in-time correct, survivorship-bias-free** systematic research and backtesting platform for Indian equities (NSE/BSE).

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![DuckDB](https://img.shields.io/badge/DuckDB-Parquet-orange)
![Tests](https://img.shields.io/badge/Tests-78%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)


## What This Does

IndiQuant ingests historical Indian market data, computes quantitative factors organised into six research pillars (Quality, Valuation, Growth, Financial Health, Momentum, Ownership), and will backtest whether composite stock scores predict forward returns — with the **full Indian statutory cost stack**, not a flat commission approximation.

The platform is designed to answer one question: **"If you had ranked stocks by a Tapetide-style composite score every month for 10 years, would the top decile have beaten the bottom decile — after real costs?"**

### Why It's Hard (And Why This Exists)

Most backtesting tools for Indian equities silently produce wrong answers because of three biases:

| Bias | The Problem | How IndiQuant Prevents It |
|---|---|---|
| **Survivorship** | Testing on today's NIFTY 50 ignores companies removed after crashing | Historical index membership from 2012, including all removals |
| **Lookahead** | Using Q2 earnings in a June signal, before results were published in August | Every data point has a `knowledge_date`; access enforced via `as_known_on()` |
| **Wrong Costs** | Modeling Indian costs as "0.1% commission" (India has 7+ separate statutory charges) | Each charge modeled individually with date-effective rates |

## Current Status

### ✅ Phase 1 — Data Ingestion (Complete)

A `Source` base class provides a standardised pipeline: **fetch → parse → validate → land (bronze) → promote (silver)**.

| Source | Table | Rows | Date Range | Status |
|---|---|---|---|---|
| NSE Equity Bhavcopy | `equity_daily` | 3,919,719 | 2016-03 → 2024-12 | ✅ Backfilled |
| NSE Corporate Actions | `corporate_actions` | 21,959 | 2015-01 → 2024-12 | ✅ Backfilled |
| NIFTY 50 History (Wikipedia) | `index_membership` | 77 intervals | 2012-01 → 2025-09 | ✅ Survivorship-free |
| yfinance Smoke Test | `fundamentals_smoke` | 54 | Recent quarters | ✅ Smoke test only |
| NSE F&O Bhavcopy | `derivatives` | 243,525,636 | 2016-03 → 2024-12 | ✅ Backfilled |
| NSE Participant OI | `participant_oi` | 10,880 | 2016-05 → 2024-12 | ✅ Backfilled |
| NSE FII/DII | `fii_dii` | — | — | ⛔ No viable free historical source |
| NSE Bulk/Block Deals | `bulk_block_deals` | — | — | ⛔ Historical API WAF-blocked |
| NSE Shareholding | `shareholding` | — | — | 🔲 Not attempted |
| NSE Fundamentals | `fundamentals` | — | — | ⛔ No free PIT-correct source |

Every silver row carries provenance: `source`, `ingested_at`, `raw_hash`, `knowledge_date`.

### ✅ Phase 2 — Lakehouse Storage (Complete)

- **DuckDB over Hive-partitioned Parquet** (`year=YYYY/data_{uuid}.parquet`)
- **Atomic appends** — each write creates a uniquely-named file via `os.rename()`. No data loss on mid-write crash.
- **Point-in-time queries** via `store.pit.as_known_on(date)` — enforces `knowledge_date ≤ as_of_date`
- **Schema validation** with Pandera on every ingested DataFrame

### ✅ Phase 3 — Factor Library (Foundations Complete)

- **`@factor` decorator + `FactorRegistry`** — registers factors with metadata (pillar, direction, required tables)
- **`FactorContext`** — the only way factors can access data; prevents lookahead by routing through `as_known_on()`
- **Transforms:** `winsorize` (symmetric clipping), `z_score`, `rank_normalize` — all unit-tested with hand-computed values
- **Composite score:** pillar-weighted scoring with floor logic (rescales weights when pillars are missing; masks if below `min_pillars`). **Caveat**: The composite score must not be presented as "the Tapetide six-pillar composite" in any UI, demo, or outreach material until more than 2 of 6 pillars are real.
- **Registered factors:** `momentum_12_1` (fully live and wired to real equity data), `roce_ttm` (structurally real but blocked by missing historical fundamentals data before 2025-02-14).

### ✅ Phase 4 — API Integration (Complete)

- **FastAPI REST Layer**: Serves data with validation (Pydantic v2). Includes authentication and error handling.
- **Render Deployment**: Fully automated Infrastructure as Code (`render.yaml`) for deploying the web service, background workers, and PostgreSQL metadata DB.

### ✅ Phase 5 — Anti-Overfitting & Trial Registry (Complete)

- Append-only Trial Registry with `content_hash` deduplication and `data_provenance` gating.
- Deflated Sharpe Ratio (DSR) using raw kurtosis variance modeling.
- Purged Walk-Forward Cross-Validation with explicit embargo constraints.
- PBO calculation structure defined but explicitly masked pending multi-factor capabilities.

### 🔄 Phase 6 — Advanced Analytics & Derivatives (In Progress)
- **F&O Bhavcopy:** ✅ Backfilled and PIT-validated (`get_fo_contracts` implemented).
- **Participant OI:** ✅ Backfilled and PIT-validated (2,176 trading days, 2016-2024; two documented NSE-side rounding artifacts bounded to ±2 contracts).
- **FII/DII Cash Flow:** ⛔ Investigated — blocked, no viable free historical source for the full FII+DII cash-market scope as of 2026-09-30. NSE live API blocks historical queries; legacy NSE/BSE archive endpoints are dead; SEBI's FPI archive is scope-mismatched (FPI-only, includes primary market).
- **Bulk/Block Deals:** ⛔ Investigated — historical backfill blocked by endpoint-specific WAF (`/api/historical/bulk-deals` returns 503 even with cookie priming that works for corporate_actions). Live snapshot works for current-day only; forward capture out of scope since it can't populate the 2017-2024 backtest window.
- **Shareholding:** 🔲 Not attempted, deprioritized — expected to face the same WAF constraints as bulk/block deals and FII/DII.
- **Derivatives-based Factors:** 🔲 Not started (e.g. OI buildup classification). Only raw contract-level backfill and PIT-safe retrieval is complete; no analytics or F&O cost modeling is implemented yet.

### ✅ Phase 7 — Statutory Cost & Execution Engine (Complete)
- Full Indian cost model (7 statutory charges including STT, Exchange, SEBI, Stamp Duty, DP, GST with date-effective rates).
- Clean mathematical separation between Real (cost-adjusted) and Paper (zero-cost) portfolios.

### ✅ Phase 8 — AI Agent Integration (MCP) (Complete)
- **MCP Server (TypeScript)**: Model Context Protocol integration, allowing AI agents direct access to factor data, universe construction, and backtesting.
- **Verified Working:** Both Stdio and remote HTTP+SSE transports successfully round-trip tool calls (e.g., `run_backtest`, `list_factors`). 
- **Security:** HTTP+SSE transport enforces Bearer token authentication against configured environment variables.
- **Shaping:** Enforces token budgeting via `shaping.ts` across both transports to prevent AI context overflow.

### ✅ Phase 9 — Cross-Sectional Backtesting (Complete)
> **Note:** The Phase 9.1 engine update successfully fixed historical "split amnesia" (where old ISIN histories were stranded). The engine now correctly stitches ISINs and applies point-in-time backward split/bonus adjustments without lookahead bias, restoring the survivorship-free NIFTY 50 universe. While `index_membership` coverage extends from 2012–2024, factor-based backtesting is only valid from **~2017-03 onward** because `equity_daily` price data begins in 2016-03, requiring a ~380-day lookback buffer to compute the first valid momentum factors.

**Current Architecture Layers (Phase 9.1):**
- **Data Layer**: DuckDB over partitioned Parquet, Postgres for metadata, 3-state gap classifier, trading calendar derived from bhavcopy gaps.
- **Identity Layer**: `security_id` serves as the stable primary key for index membership. The `isin_chain` table resolves a `security_id` to its active ISIN as of a given `knowledge_date`. (This replaces the earlier approach of hardcoding ISINs directly in `index_membership`).
- **Price Layer**: `get_adjusted_prices` (in `store/pit.py`) applies a cumulative split/bonus adjustment from `corporate_actions`. It is point-in-time safe (only applies actions with `ex_date <= asof`) and is completely agnostic to whether the adjustment coincides with an ISIN change. (Both split and bonus mathematical structures are fully validated).
- **Derivatives Layer**: `get_fo_contracts` (in `store/pit.py`) resolves an ISIN to its continuous `security_id` via `isin_chain`, then fetches all F&O rows for any symbol historically associated with that identity within the requested date range.
- **Universe Validation**: The `BacktestEngine.run()` method enforces a strict `ValueError` guard. All constituents *must* have valid factor history unless explicitly listed in `MISSING_DATA_WAIVERS`. True structural exceptions (JIOFIN demerger, LTIM merger, BAJAJHLD) are explicitly waived.

### ✅ Phase 10 — Production Reporting (Complete)
- `FactorContext` + `decile-report` CLI command for generating PDF tearsheets.
- Automated daily strategy tracking.

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Type hints, pattern matching |
| Package Manager | uv + Hatchling | Fast, lockfile-based reproducibility |
| API Layer | FastAPI, Pydantic v2 | High-performance async REST, built-in validation |
| MCP Layer | TypeScript, @modelcontextprotocol | Exposes lakehouse directly to AI agents |
| Deployment | Render | PaaS with persistent disk for DuckDB storage |
| Ingestion | Polars, httpx | Zero-copy CSV parsing, async HTTP |
| Research | pandas 2.x, NumPy | Ecosystem compat with vectorbt |
| Storage | DuckDB over Parquet | In-process columnar analytics, ASOF JOINs |
| Schema Validation | Pandera (Polars backend) | Declarative column-level checks |
| CLI | Typer | Type-safe args, auto `--help` |
| Config | Pydantic v2 + pydantic-settings | Validates `.env` at startup |
| Logging | structlog | Structured JSON, machine-parseable |
| Retry | tenacity | Exponential backoff for NSE rate limits |
| Linter | ruff | Replaces flake8 + isort + black |
| Type Checker | mypy --strict | Catches errors before runtime |
| Tests | pytest | 78 tests, strict markers |

## Project Structure

```
src/indiquant/
├── api/                  # FastAPI REST layer (App, Auth, Errors, Freshness)
├── cli/                  # `iq` CLI entry point (Typer)
├── config/               # Pydantic settings (.env-based)
├── ingest/               # Data ingestion pipeline
│   ├── base.py           # Source base class (fetch→parse→validate→land→promote)
│   ├── backfill.py       # Sequential date-range backfill engine
│   ├── calendar.py       # Trading calendar derivation
│   ├── cli.py            # `iq ingest backfill/status` commands
│   ├── models.py         # RawPayload, ValidationReport
│   ├── sources/          # Concrete Source implementations
│   └── adapters/         # Broker adapters (Kite, Dhan stubs)
├── store/                # DuckDB/Parquet lakehouse
│   ├── lakehouse.py      # read_table, write_bronze, write_silver
│   ├── pit.py            # Point-in-time resolution (as_known_on)
│   └── schemas.py        # Pandera schemas + _ProvenanceMixin
├── factors/              # Factor library
│   ├── base.py           # @factor decorator, FactorRegistry, FactorContext
│   ├── transform.py      # winsorize, z_score, rank_normalize
│   ├── composite.py      # Pillar-weighted composite score
│   ├── quality.py        # ROCE TTM factor
│   └── momentum.py       # 12-1 month momentum factor
├── universe/             # Universe construction
│   ├── builder.py        # Universe from historical index membership
│   ├── adjust.py         # Corporate action adjustments
│   ├── membership.py     # Historical membership resolution
│   ├── liquidity.py      # ADV-based liquidity filters
│   └── delisting.py      # Delisting event handling
├── costs/                # Indian statutory cost model
│   ├── engine.py         # Cost deduction and Real/Paper split
│   ├── rates.py          # Time-dated statutory rates
│   ├── slippage.py       # ADV-based slippage functions
│   └── statutory.py      # STT, stamp duty, exchange fees
├── backtest/             # Cross-sectional backtest engine
│   ├── engine.py         # Portfolio simulation, pro-rata scaling
│   └── models.py         # BacktestResult, Position, TargetWeight
├── validation/           # Anti-overfitting harness
│   ├── registry.py       # Append-only trial registry (SQLite/DuckDB)
│   ├── deflated_sharpe.py# DSR computation based on trial count
│   ├── walk_forward.py   # Purged CV with embargo
│   ├── multiple_testing.py# Family-wise error rate adjustments
│   └── pbo.py            # Probability of Backtest Overfitting
├── report/               # Tearsheets (planned)
└── logging.py            # structlog config

mcp-server/               # TypeScript MCP Server for AI integration
tests/                    # 78 tests across all modules
scripts/                  # Utility scripts (backfill, coverage checks)
render.yaml               # Render Infrastructure as Code definition
Dockerfile                # Unified runtime for API and background jobs
```

## Quick Start

### Prerequisites
- Python 3.12
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js (for MCP server)

### Installation

```bash
git clone <repo-url>
cd indiquant
uv sync
```

### CLI Commands

```bash
# Run backfill for a specific source
uv run iq ingest backfill --from 2020-01-01 --to 2024-12-31 --source nse_equity_daily

# Check lakehouse status
uv run iq ingest status

# Derive trading calendar from bhavcopy coverage
uv run iq ingest derive-calendar --from 2016-01-01 --to 2024-12-31
```

### Run Tests

```bash
uv run pytest
```

## Data Sources

All data comes from **free, public endpoints**. No paid API keys are used.

| Source | Endpoint | Auth |
|---|---|---|
| NSE Bhavcopy | `nsearchives.nseindia.com` | Cookie priming (no key) |
| NSE Corporate Actions | `www.nseindia.com/api/` | Cookie priming (no key) |
| NIFTY 50 History | Wikipedia structured table | None |
| Fundamentals (smoke) | yfinance | None |

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `security_id` as primary identity | NSE reuses symbols (e.g., `VEDL` was `SESAGOA`) and issues new ISINs on splits. `security_id` anchors index membership stably across events. |
| ISIN for point-in-time joins | Historical prices (`equity_daily`) and fundamentals are strictly stored and queried using the ISIN active at that date. |
| Polars for ingestion, pandas for research | Polars is faster for I/O-heavy parsing; pandas for vectorbt ecosystem compatibility. |
| UUID-named Parquet files per write | Prevents DuckDB `OVERWRITE_OR_IGNORE` from wiping partition directories. |
| 200-day max staleness for fundamentals | An 11-month-old quarterly result is barely different from missing data. No median imputation. |
| `knowledge_date` on every row | The single field that prevents lookahead bias across the entire system. **Caveat**: For F&O data from 2016-2018, the NSE server migration in 2019 overwrote timestamps, making `knowledge_date = trade_date` an inference drawn from post-2019 consistency rather than a mathematically proven fact for those specific years. |

## License

MIT
