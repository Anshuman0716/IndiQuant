# IndiQuant

A **point-in-time correct, survivorship-bias-free** systematic research and backtesting platform for Indian equities (NSE/BSE).

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![DuckDB](https://img.shields.io/badge/DuckDB-Parquet-orange)
![Tests](https://img.shields.io/badge/Tests-46%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

## 🚀 Live Demo

The API is currently deployed live on Render!
- **Interactive API Docs (Swagger UI):** [https://indiquant-api.onrender.com/docs](https://indiquant-api.onrender.com/docs)
- **Health Check:** [https://indiquant-api.onrender.com/v1/health](https://indiquant-api.onrender.com/v1/health)

*(Note: Deployed on Render's Free tier. The first request may take up to 50 seconds if the container has spun down due to inactivity).*

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
| NSE F&O Bhavcopy | `derivatives` | — | — | 🔲 Source built, not backfilled |
| NSE Participant OI | `participant_oi` | — | — | 🔲 Source built, not backfilled |
| NSE FII/DII | `fii_dii` | — | — | 🔲 Source built, not backfilled |
| NSE Bulk/Block Deals | `bulk_block_deals` | — | — | 🔲 Source built, not backfilled |
| NSE Shareholding | `shareholding` | — | — | 🔲 Source built, not backfilled |
| NSE Fundamentals | `fundamentals` | — | — | ⛔ NSE API blocked for historical data |

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
- **Composite score:** pillar-weighted scoring with floor logic (rescales weights when pillars are missing; masks if below `min_pillars`)
- **Registered factors:** `momentum_12_1`, `roce_ttm` (computation stubs ready for real data hookup)

### ✅ Phase 4 — API & MCP Integration (Complete)

- **FastAPI REST Layer**: Serves data with validation (Pydantic v2). Includes authentication and error handling.
- **MCP Server (TypeScript)**: Model Context Protocol integration, allowing AI agents direct access to factor data, universe construction, and backtesting.
- **Render Deployment**: Fully automated Infrastructure as Code (`render.yaml`) for deploying the web service, background workers, and PostgreSQL metadata DB.

### 🔲 Pending

- Full Indian cost model (7 statutory charges with date-effective rates)
- Backtest engine (vectorbt + custom event loop)
- `decile-report` CLI command

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
| Tests | pytest | 68 tests, strict markers |

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
│   ├── sources/          # 10 concrete Source implementations
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
├── costs/                # Indian statutory cost model (planned)
├── engine/               # Backtest engine (planned)
├── report/               # Tearsheets (planned)
└── logging.py            # structlog config

mcp-server/               # TypeScript MCP Server for AI integration
tests/                    # 68 tests across all modules
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
| ISIN as primary key, never ticker | NSE reuses symbols (e.g., `VEDL` was `SESAGOA`). Joining on symbol silently loses history. |
| Polars for ingestion, pandas for research | Polars is faster for I/O-heavy parsing; pandas for vectorbt ecosystem compatibility. |
| UUID-named Parquet files per write | Prevents DuckDB `OVERWRITE_OR_IGNORE` from wiping partition directories. |
| 200-day max staleness for fundamentals | An 11-month-old quarterly result is barely different from missing data. No median imputation. |
| `knowledge_date` on every row | The single field that prevents lookahead bias across the entire system. |

## License

MIT
