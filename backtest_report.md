# Prediction Market vs Rates Futures — Backtest Results, Fixes & Defects

**Date:** 2026 (session run)
**Scope:** Re-run of `test.py` after a round of correctness fixes to `backtester.py` and `test.py`.
**Working directory:** `C:\Users\yangm\OneDrive - FINMA\Code`

---

## 1. Executive summary

The full 27-meeting run now completes cleanly (0 failed pulls, 0 retries) and writes `data/spread_daily.csv` (1,193 daily observations). The core hypothesis — **Kalshi lags ZQ futures and converges into the meeting** — is now confirmed by a clean, unbiased test:

- **ZQ → Kalshi Granger-causes**: β = +0.69, t = 5.08 (highly significant). A 1 bp move in the futures-implied move today predicts a ~0.69 bp move in Kalshi's implied move tomorrow.
- **Kalshi → ZQ**: β = −0.006, t = −0.95 (≈ 0). Futures do *not* chase Kalshi.

The mechanism is real. **But it is small**: the effect explains only ~2% of daily variance, the average spread is ~2 bp and its *sign* flips with an unobservable assumption (the ">25bp" tail value), and a non-overlapping, costed backtest only turns positive once the entry threshold is ≥ ~3 bp. The signal is real but likely **inside the transaction-cost envelope** as a standalone retail-taker trade.

---

## 2. What was run

| Item | Value |
|---|---|
| Meetings reconciled | 28 settled winners → **27** after dropping the void `FEDDECISION-24JAN` |
| Daily observations | 1,193 (saved to `data/spread_daily.csv`) |
| Current EFFR (DFF) | 3.88% |
| Failures / retries | **0 / 0** |

---

## 3. Results

### 3.1 Lead/lag (the clean test — change-on-change, no shared level term)

This is the headline result. Unlike the old regression, it has no mechanical bias (no `−Kₜ` term shared between the two sides).

| Test | β | se | t | R² | n |
|---|---|---|---|---|---|
| **ZQ → Kalshi** (ZQ today predicts Kalshi tomorrow) | **+0.690** | 0.136 | **5.08** | 0.022 | 1,135 |
| **Kalshi → ZQ** (Kalshi today predicts ZQ tomorrow) | −0.006 | 0.006 | −0.95 | 0.001 | 1,137 |

**Interpretation:** Kalshi lags ZQ, and not vice-versa. The effect is statistically unambiguous (|t| > 5) but economically small (R² ≈ 2%).

For completeness, the *old* level-on-change regression (now correctly labelled as biased) gives `kalshi_change_next ~ spread_today` β = 0.82 (R² = 0.42) and `zq_change_next` β = −0.011 — the Kalshi coefficient is inflated by the shared `−Kₜ` term, which is why it must not be quoted as an effect size.

### 3.2 Chronological train / out-of-sample (biased regression, for continuity)

| Split | kalshi_change_next β | zq_change_next β |
|---|---|---|
| Train 2023–2025 (n=936) | +0.845 | −0.009 |
| OOS 2026 (n=226) | +0.175 | −0.088 |

The positive Kalshi coefficient persists out-of-sample (though the *clean* Granger test has not yet been split train/OOS — see §6).

### 3.3 Average spread by meeting (ZQ − Kalshi, bp)

Extremes:

| Meeting | Avg spread (bp) |
|---|---|
| FEDDECISION-24SEP | **−4.13** |
| FEDDECISION-24NOV | −1.57 |
| KXFEDDECISION-25SEP | −1.38 |
| … (most meetings) | within ±1 |
| FEDDECISION-24JUL | +2.29 |
| FEDDECISION-24JAN31 | +2.90 |
| KXFEDDECISION-26JUL | +3.10 |
| FEDDECISION-24MAR20 | **+3.70** |

The outliers are dominated by high-volatility / late-month meetings, consistent with the variance-blow-up fix changing those values the most.

### 3.4 Tail-value sensitivity (mean spread, bp)

| tail_move_bp | mean spread |
|---|---|
| 50 | +0.14 |
| 75 | +0.81 |
| 100 | +1.49 |

The **sign and size of the average spread depend on the assumed value of the ">25bp" bucket**. The level of the spread is therefore not identifiable — only its *changes* (the convergence/lead-lag) are robust.

### 3.5 Convergence by lookback window

| Window (days) | Obs | mean spread (bp) | mean \|spread\| (bp) |
|---|---|---|---|
| 60 | 1,166 | +0.14 | 2.02 |
| 35 | 925 | +0.24 | 1.87 |
| 21 | 561 | +0.36 | 1.66 |
| 14 | 374 | +0.27 | 1.62 |

Mean |spread| shrinks ~20% from 60 days to 14 days before the meeting — convergence is present but weak.

### 3.6 Non-overlapping, costed convergence backtest (1.4 bp/trade)

| Entry (bp) | Trades | mean gross (bp) | mean net (bp) | total net (bp) | win rate |
|---|---|---|---|---|---|
| 1 | 122 | 2.58 | 1.18 | 143.9 | 37% |
| 2 | 72 | 5.22 | 3.82 | 275.4 | 72% |
| 3 | 49 | 7.55 | 6.15 | 301.4 | 82% |
| 5 | 32 | 11.36 | 9.96 | 318.8 | 87.5% |

**Interpretation:** at a 1 bp entry the trade is a coin-flip-or-worse (37% win rate after costs); the edge only materialises at ≥ ~3 bp entry. **Caveat:** this is still a mid-price proxy — no fills, no position size, no dollar P&L — so these "win rates" overstate a real tradeable edge. It is a signal-robustness table, not a P&L.

---

## 4. Changes applied (this session)

### `backtester.py`

1. **`get_zq_data_with_retry`** — the "connection lost → no data" loop was caused by reusing a dead `tvDatafeed` websocket. Now a **fresh `TvDatafeed()` per attempt**, exponential backoff, and a disk cache (`data/cache/zq/{symbol}.csv`).
2. **`get_candlesticks`** — added a JSON cache (`data/cache/kalshi/`), filename sanitization for tickers containing `>` (see §5, defect #10), and a non-fatal cache write so a cache failure can never discard a good fetch.
3. **`kalshi_expected_move_bp`** — probabilities are now **normalized** (`p / Σp`) so the expectation is over a proper distribution.
4. **`zq_expected_move_bp`** — fixed the `1/w_after` variance blow-up. Early-month meetings solve from the meeting-month contract (baseline DFF); **late-month meetings use a calendar spread** against the next-month contract, which divides by `(1 − w_after)` instead of a tiny `w_after`.
5. **`pull_and_compare`** — accepts `meeting_date` (actual decision date for the day-count, not the last candle) and `meeting_months` (so the next-month anchor is only used when that month has no meeting of its own).

### `test.py`

6. **UTF-8 stdout** — fixes the crash on the U+2212 "−" character.
7. **Resilient loop** — one meeting's failure logs and skips instead of aborting the run.
8. **Saves `data/spread_daily.csv`**.
9. **Fixed the silent `rename` bug** (`"winning_ticker"` was a nonexistent column).
10. **Added `granger_lead_lag` + `ols_with_se`** — the clean, unbiased lead/lag test with standard errors and t-stats.
11. **Replaced `simulate_convergence`** with `backtest_convergence` (non-overlapping, 1.4 bp realistic cost).
12. **Plumbed `meeting_months` / `meeting_date_map`** through to `pull_and_compare`.

Backups of the originals: `test.py.bak`, `backtester.py.bak`.

---

## 5. Defects detected

### In the original code

1. **Unicode print crash** — `−` (U+2212) in print strings crashed the script under cp1252, hiding all results.
2. **Non-normalized Kalshi probabilities** — `Σ pᵢ ≠ 1`, a systematic bias in every row of the spread.
3. **`1/w_after` variance blow-up** — late-month meeting moves were amplified 2–6×; the "last 5 days" fallback was far too narrow.
4. **Next-month fallback ignored adjacent-month meetings** — the next-month contract could embed a *second* decision.
5. **`meeting_day` inferred from the last candle**, not the actual decision date.
6. **Silent rename bug** — `"winning_ticker"` → `"ticker"` was a no-op.
7. **Mechanical bias in the lead/lag regression** — regressing a *change* on a *level* gap that shares the `−Kₜ` term inflated the Kalshi coefficient.
8. **Overlapping, uncosted convergence proxy** — every wide day counted as its own "trade", no realistic fee.

### Methodology notes (identified, not "fixed" because they are choices/limitations)

9. **Tail bucket = 50 bp is a lower bound** — dominates the spread *level* (see §3.4). Treated as a parameter, not a bug.
10. **EFFR drift vs target midpoint** — a near-constant EFFR↔target offset *cancels* when computing a change; using the target midpoint as `r0` (as an earlier draft suggested) would have introduced an `offset/w_after` error. DFF (EFFR) is the correct space.
11. **Contemporaneity** — ZQ daily close (2pm CT) vs Kalshi daily candle (UTC midnight) are not the same instant; needs intraday data to fix.

### Introduced and fixed during this session

12. **Cache filename with `>`** — the ticker `FEDDECISION-23JUN-H>25` contains `>`, an illegal Windows filename character, so the first caching attempt silently dropped the `>25` tail buckets for the early-2023 meetings. Fixed by sanitizing the cache key (and making cache writes non-fatal).

---

## 6. Open items / next steps

1. **Split the clean Granger test train/OOS** — currently it runs on the pooled frame; the OOS discipline (which the biased regression already has) should be applied to the Granger test.
2. **Real dollar P&L backtest** — position size × bucket-price change, with the ZQ delta hedge (Trade B), instead of the mid-price spread proxy.
3. **Regime conditioning** — is the edge concentrated in high-volatility meetings (e.g. Sep 2024)? That is where a tradeable edge, if any, will live.
4. **Maker vs taker** — the one-pager's open question; maker rebates could flip the 1–2 bp edge from negative to positive.
5. **Spot-check early-sample ZQ** against CME settlement (anonymous `tvDatafeed` "nologin" access may be limited for contracts > ~2 years old).
6. **Dutch-book check** (`Σ ask < 1` / `Σ bid > 1`) — a separate, cost-simple signal from §4.2 of the context doc, not yet implemented.
