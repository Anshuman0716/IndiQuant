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

## Known Limitations

### 1. Split Amnesia (Unstitched ISINs)
**Status:** Known limitation, deferred to future data ingestion phases.
**Blast Radius:** 100% of all monthly rebalance periods between 2017 and 2024 are affected.

**Description:**
When an Indian listed company undergoes a stock split, it is frequently issued a new ISIN. The platform's `index_membership` table maps index constituents accurately to their *current* (or valid-at-the-time) ISIN on any given knowledge date. However, the `equity_daily` table stores historical prices strictly under the exact ISIN that was active on the day the trade occurred.

Because the lakehouse does not proactively stitch old ISINs to new ISINs across corporate actions, fetching lookback data for a post-split entity (e.g., fetching 380 days of history for the new ISIN) will fail to find the prices recorded prior to the split under the old ISIN.

**Impact on Factor Accuracy:**
- **Understated Valid Universe:** Any stock that undergoes a split drops out of any factor calculation requiring a historical lookback (e.g., `momentum_12_1` which requires 380 days) for the duration of the lookback window.
- **Smaller Effective Universe:** This artificially shrinks the valid NIFTY 50 universe from exactly 50 down to between 41 and 49 constituents in every single month of the 2017-2024 backtest.
- **Cross-Phase Impact:** This affects *every* phase or module that consumes `equity_daily` lookback history, not just Phase 9.

**Resolution Plan:**
This requires a data engineering fix in the ingestion layer (mapping historical ISINs to current ISINs using the `corporate_actions` table) rather than a workaround in the cross-sectional backtest engine.

### 2. Fundamentals Coverage Gap
**Status:** Known limitation.

**Description:**
Some newer listings or specific index additions lack complete fundamental data coverage matching their equity price histories.

**Impact:**
Factor calculations requiring fundamental inputs (like `roce_ttm`) will exclude these constituents, leading to a smaller valid universe similar to the split amnesia effect.

### 3. Participant OI Checksum Errors (Two Distinct Modes)
**Status:** Known NSE data-quality caveat.

**Description:**
In the NSE's raw Participant OI data, the `TOTAL` row does not always mathematically equal the sum of the institutional constituents (`Client`, `DII`, `FII`, `Pro`). Across the 2016-2024 history, 821 trading days (37.7%) exhibit mismatched totals, bounded to exactly 1 or 2 contracts. Analysis reveals two entirely distinct failure modes originating from the exchange:

1. **Stochastic Vertical Mismatches (Pre-June 2021):**
   Prior to mid-2021 (notably in 2018), the NSE occasionally published files where a specific instrument bucket (e.g., `opt_idx_call_long`) failed the vertical sum by 1 contract. The exchange then horizontally summed this flawed column to produce `total_long`. The `TOTAL` row was horizontally consistent with itself, but vertically inconsistent with the constituents. This failure was rare and scattered.

2. **Structural Horizontal Mismatches (Post-June 25, 2021):**
   Beginning exactly on June 25, 2021, a new, permanent failure mode emerged (hitting a 100% daily failure rate in 2022). In this mode, the vertical sum for *every individual instrument bucket* is perfectly correct. However, the `total_long` column within the `TOTAL` row is strictly horizontally inconsistent with its own row's buckets by 1 contract, and therefore vertically inconsistent with the constituent `total_long` sums. This indicates a structural formula/aggregation bug introduced into the NSE's backend reporting on that date.

**Impact:**
Because both error modes are strictly bounded to an absolute maximum of ±2 contracts out of millions, the impact on any systematic flow factor is statistically zero. The lakehouse ingests exactly what the NSE publishes without attempting to "correct" the exchange's arithmetic.

### 4. FII/DII Cash Market Historical Data Unavailability
**Status:** Known source unavailability constraint.

**Description:**
The original scope for the `nse_fii_dii` data ingestion targeted the combined, daily secondary cash market flows for both Foreign Institutional Investors (FII) and Domestic Institutional Investors (DII) from 2016 onward. However, there is no viable free historical source for this exact scope as of September 2026:
- The NSE live API (`api/fiidiiTradeReact`) provides the correct FII+DII cash market scope, but aggressively blocks historical date queries (returning 503s or ignoring parameters).
- Both legacy archive endpoints (`nseindia.com/content/equities/eq_fiidii_archives.htm` and `bseindia.com/markets/Derivatives/DeriReports/FIISummaryHistorical.aspx`) are dead/redirected.
- SEBI's official FPI archive provides viable, final T+1 knowledge-dated data back to 1999, but its scope is mismatched: it covers FPIs only (lacking DIIs) and includes primary market flows (rather than being strictly secondary market).

**Impact:**
The `nse_fii_dii` historical backfill is permanently blocked until a proprietary offline archive or new public endpoint is identified. SEBI's FPI archive is explicitly documented as a viable but *structurally different* dataset, and is intentionally NOT substituted here to preserve the strict secondary-market FII+DII scope intended for this module.

### 5. Bulk/Block Deals Historical Data Unavailability
**Status:** Known endpoint-specific WAF block, confirmed September 2026.

**Description:**
The NSE historical API for bulk and block deals (`/api/historical/bulk-deals` and `/api/historical/block-deals`) returns HTTP 503 with an Akamai WAF block page, even when using the exact same cookie-primed `httpx` session that successfully retrieves data from the corporate actions API (`/api/corporates-corporateActions`) in the same request sequence. This is a **per-endpoint** block, not a session or authentication issue. All historical CSV URL patterns on `nsearchives.nseindia.com` return 404.

**What works (current-day only):**
- The live snapshot API (`/api/snapshot-capital-market-largedeal`) returns JSON with `BULK_DEALS_DATA`, `BLOCK_DEALS_DATA`, and `SHORT_DEALS_DATA` for the current trading session.
- The S3 archive CSVs (`nsearchives.nseindia.com/content/equities/bulk.csv` and `block.csv`) serve current-day data, published same-day evening (~19:27 IST, confirmed via `Last-Modified` headers).

**Impact:**
Forward capture is technically possible but explicitly out of scope: the platform's backtest window is 2017–2024, and a forward-only pipeline cannot populate that window. Historical backfill is blocked until a proprietary archive or new endpoint is identified.

### 6. Fundamentals Coverage Gap
**Status:** Known limitation, no viable free PIT-correct source identified.

**Description:**
Historical fundamental data (revenue, EBITDA, PAT, etc.) is required by 7 registered-but-idle factors (`roce_ttm`, `roe_ttm`, `gross_profitability`, `opm_stability`, and 3 others). Four candidate sources were investigated:
- **Screener.in / Tijori Finance:** Provide quarter-end-dated figures only (e.g., "Sep 2023"), not the actual filing/publication date. This introduces severe lookahead bias and violates Rule #1 (Point-in-Time). Both are also WAF-protected (Cloudflare).
- **BSE Historical Filings:** Carry exact filing timestamps (PIT-correct), but require Akamai WAF bypass and parsing unstructured PDFs/HTML — a multi-week engineering effort.
- **XBRL Filings (BSE/NSE):** The gold standard for PIT-correct structured data, available since ~2015. Requires WAF bypass for download links plus specialized XML taxonomy parsing (`Arelle`, `py-xbrl`) across evolving schemas. Assessed as very-high-effort.

**Impact:**
The 7 fundamental factors remain idle. If fundamentals become a priority, BSE XBRL filings are the recommended path — but this is a standalone project, not a quick backfill task. The `yfinance` smoke test source remains available for structural validation only and must not be used for backtesting.
