# Key Decisions & Principles

## 2026-09-29: Reconciling `security_id` vs. ISIN-as-Primary-Key

**Context:** 
The original project architecture mandated that all joins happen strictly on ISIN to prevent survivorship bias and symbol-reuse errors ("ISIN IS THE PRIMARY KEY"). As a result, the early `index_membership` pipeline hardcoded active ISINs directly alongside the symbols.

However, companies change ISINs during corporate actions (splits, bonuses). In Phase 9.1, it was discovered that joining purely on a static ISIN stranded lookback history for split entities (the "Split Amnesia" bug), fracturing a single constituent into two distinct entities in the lakehouse.

**Decision:**
To support continuous time-series while maintaining rigorous point-in-time constraints, we introduce `security_id` as the stable surrogate key representing the continuous economic entity.

**How it works:**
1. **Stable Surrogate Key:** `index_membership` tracks the constituent via `security_id` (derived from connected components of historical ISIN/Symbol transitions).
2. **Time-Bound Mapping:** A new dimension table, `isin_chain`, explicitly maps the `security_id` to its active `isin` via `valid_from` and `valid_to` bounds.
3. **Point-In-Time Integrity:** When pulling equity prices or fundamentals, the system queries `isin_chain` as of the `knowledge_date` to resolve the *exact ISIN* that was active on the day the trade occurred.

**Why this preserves our principles:**
This explicitly **supersedes** the earlier "hardcode ISIN into index_membership" approach. However, it **does not violate** the original "never join on ticker/symbol" principle. Symbols remain purely display attributes. The underlying data joins (e.g., in `equity_daily`) still resolve natively to the historical ISIN via the `isin_chain` mapping layer. The architecture drift is now formalized.

## 2026-09-29: Caveat regarding F&O `knowledge_date` for 2016-2018

**Context:**
The core tenet of the platform is that all financial data must be point-in-time correct, meaning `knowledge_date` (the time data became publicly available) governs all queries. For daily market data (OHLCV, Derivatives), we generally assert that `knowledge_date = trade_date` (the data is published at EOD).

**Limitation Disclosure:**
For historical F&O data between 2016 and 2018, the NSE performed a massive server migration in January 2019 that overwrote the HTTP `Last-Modified` timestamps of all prior archives. Therefore, for this specific 2016-2018 window, the assumption that `knowledge_date = trade_date` is **technically unproven** by cryptographic or header evidence. It is a structurally sound inference drawn from post-2019 EOD publication consistency, but we honestly disclose it as an inference, similar to other known data limitations.
