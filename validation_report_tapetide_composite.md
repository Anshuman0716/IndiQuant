# Anti-Overfitting Report: tapetide_composite

## 1. Trial Registry
- **Total Logged Trials:** 9
- **OOS Status:** SEALED
- **Note on Backfill:** The count includes 8 reconstructed trials from implicit zero-shot design decisions made prior to registry enforcement.

## 2. Statistical Significance & DSR Sensitivity
**Observed Annualized Net Sharpe:** 0.24 (2023)
**Variance of Annualized Sharpes:** 1.0 (Textbook Assumption)
**Skewness:** 0.988  
**Kurtosis:** 8.465

| Assumed Trial Count | Expected Max SR (sr0) | Deflated Sharpe Ratio (DSR) |
|---------------------|-----------------------|-----------------------------|
| 1                   | 0.00                  | 0.5947                      |
| 5                   | 1.19                  | 0.0210                      |
| 10                  | 1.57                  | 0.0028                      |
| 25                  | 2.00                  | 0.0001                      |
| 50                  | 2.28                  | 0.0000                      |

**Conclusion on Significance:** The raw Sharpe is barely positive. With just 9 trials logged, the DSR drops virtually to zero. The strategy is entirely noise.

## 3. Robustness
### 3.1 Walk-Forward (Real Execution)
- **2022 Fold:** -0.04 Net Sharpe
- **2023 Fold:** +0.24 Net Sharpe
- **2024 Fold:** +0.74 Net Sharpe

### 3.2 Combinatorial Purged Cross-Validation (CPCV)
Using 6 paths (2-fold combinations):
- **Mean OOS Sharpe:** 0.31
- **Median OOS Sharpe:** 0.24
- **Spread (Min/Max):** [-0.04, 0.74]
- **Probability of Backtest Overfitting (PBO):** 81%

### 3.3 Parameter Plateau Heatmap
Sweeping over `min_pillars` [2, 3, 4, 5, 6] and `rebalance_freq` [W, M, Q]:
No plateau exists. The performance is highly erratic, spiking at `min_pillars=4, freq=M` but dropping negative for all adjacent parameters. This indicates severe overfitting to a local maximum.

### 3.4 Regime Table
| Regime | Dates | Net Sharpe | Max DD |
|--------|-------|------------|--------|
| 2013 Taper Tantrum | 2013 | N/A (Data missing) | N/A |
| 2015-16 Correction | 2015-2016 | -0.84 | -31% |
| 2017 Smallcap Rally | 2017 | 1.12 | -9% |
| 2018 IL&FS Crash | 2018 | -1.55 | -41% |
| 2020 COVID Crash | Mar 2020 | -2.10 | -55% |
| 2020-21 Bull | 2020-2021 | 2.50 | -12% |
| 2022 Drawdown | 2022 | -0.04 | -22% |
| 2023-24 Rally | 2023-2024 | 0.49 | -15% |

### 3.5 Sub-Universe Stability
- **Nifty 100 Only:** -0.21 Sharpe
- **Midcap 150 Only:** 0.15 Sharpe
- **Smallcap 250 Only:** 0.65 Sharpe
The alpha strictly relies on illiquid micro-caps and breaks completely in large/mid segments.

### 3.6 Factor Attribution (IIMA Real Data)
Regressing the strategy returns on the Agarwalla/Jacob/Varma factors:
- **Alpha (const):** 0.0016 (t=0.409, **Insignificant**)
- **Mkt-Rf:** 0.1863 (t=0.385, Insignificant)
- **SMB:** -0.4135 (t=-0.724, Insignificant)
- **HML (Value):** 1.0362 (t=1.783, Marginally Significant)
- **WML (Momentum):** 0.3530 (t=0.549, Insignificant)
**Conclusion:** The strategy generates precisely zero statistically significant alpha (p=0.683). Its returns are entirely explained by underlying factor noise and beta.

### 3.7 Break-Even Cost
- **Actual Applied Cost:** ~42 bps round-trip (Brokerage, STT, Slippage, GST, etc.)
- **Break-Even Tolerance Limit:** 313 bps one-way (627 bps round-trip) required to eradicate the Gross CAGR.

## Overall Verdict
**DOES THE STRATEGY SURVIVE?** No.
The factor regression yields an insignificant alpha (t=0.409), proving the strategy is merely repackaging known factor risks (primarily HML). The Walk-Forward OOS Sharpes are abysmal (2022 is negative), the regime table shows complete failure in drawdowns (-55% in COVID, -41% in IL&FS), and the PBO is 81%. The Tapetide Composite is entirely overfit noise and must be rejected.
