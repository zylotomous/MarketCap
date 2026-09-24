# PROJECT CONTEXT: Prediction Market vs Rates Futures Arbitrage

**Course:** Markets Strategy and Trading, Capstone (FMA), 2026
**Team:** Sean Trew (strategy, documentation, planning), Nathan Yang (code, data pipeline)
**Mentor:** Richard Howes, weekly Friday check-in on Teams
**Folder:** `OneDrive - FINMA/2026/Markets Capstone/Project/`
**Last updated:** 24 Sep 2026 (Sean, with Claude)

This file is the single source of truth for the project. Anyone (or any AI assistant) should be able to read it cold and be useful. Read it before touching code or writing docs. Update it when a decision is made, a method changes or a problem is found. Keep it factual; proposals go in the memos in `docs/`.

---

## 1. What we are doing, in one paragraph

We are testing whether prediction markets (Kalshi's FOMC decision contracts) systematically diverge from the professional interest-rate futures market (CME 30-Day Fed Funds futures, ticker ZQ) in how they price Fed rate decisions, and whether that divergence is a persistent, tradeable pattern net of costs. The hypothesis is that Kalshi is thinner and slower to digest information, so it periodically lags the futures-implied view and then converges into the meeting. If true, the trade is to take the futures-implied side on Kalshi (or the Kalshi side on futures) when the gap is wide, and exit on convergence.

On the course's taxonomy this is: **systematic** decision process, **relative-value** return engine, **rates** instrument, **event-driven** archetype (each FOMC meeting is the catalyst). Primary framework: cross-market mispricing (Stage 1); central-bank reaction function (Stage 2).

Course deliverable: a **trading system** (signal, sizing, execution rules, honest backtest) with a short strategy write-up wrapping it. Submission date: **[TBC, confirm with Richard]**.

---

## 2. The two-stage roadmap

The project is deliberately staged. Stage 2 does not start until Stage 1 passes its definition of done.

### Stage 1: Kalshi vs ZQ cross-market arb, fully operational

Conceptually simple, but it has to be built properly: reproducible, cached data, correct formulas, all 26 historical meetings run, spread distribution and convergence quantified, written trade rules, a cost model, a net P&L backtest with an out-of-sample split, and a live monitor that runs on a schedule and flags when the rules fire. This is the foundation everything else sits on and it is what Richard has been asking about ("what is the trade you put on when that's the case?").

The system has two modes that share the same code: **backtest mode** replays the 26 historical meetings, and **monitor mode** runs daily against the open Kalshi meeting and the live ZQ contract, logs the spread, and alerts when a trade rule fires. Every live signal is followed to its exit in the log, so the live log is a forward paper-trading record and the real out-of-sample test.

Definition of done: see `docs/Stage 1 Definition of Done.docx`. Summary of the bar:

1. Clean-machine reproducible run (README, requirements, `.env` for keys)
2. Raw pulls cached to `data/` so TradingView instability cannot break a run
3. Formula fixes applied (threshold buckets, day-count) and unit-tested
4. Liquidity filter on Kalshi mids (wide or empty books flagged, not treated as signal)
5. All 26 meetings run to a single `spread_daily.csv`
6. Spread distribution and convergence statistics (does |spread| shrink into the meeting, and which market moves)
7. Trade rules written down: entry, exit, sizing, hedge
8. Cost model: Kalshi taker/maker fees, ZQ tick and commission, capital
9. P&L backtest, net of costs, with in-sample / out-of-sample split
10. Live monitor: scheduled daily run, signal log, alert, follow-through to exit
11. Shortcomings register up to date

### Stage 2: Reaction-function layer (Taylor rule)

Richard's steer at the 18.09 meeting. Use Kalshi's inflation (CPI) and unemployment print markets as probability distributions over the next data releases, push those through a calibrated Taylor rule, and produce a rule-implied expected policy move. Compare this to both the Kalshi FOMC EV and the ZQ EV. This gives the Stage 1 signal a *direction and a reason to converge* (which side is wrong, and why), rather than only a measurement that they differ. Course material: `class files/Taylor_Rule_document.pdf`, particularly the US parameter card (r* 0.5 to 1.0%, pi* 2.0%, NAIRU ~4.2%, Okun 2.0) and the five-step checklist (calibrate, level gap, pricing gap, identify the shock, express).

Stage 2 scope is not yet designed. Do not build it yet. A design note will be written once Stage 1 is done.

### Parked (noted, not in scope)

- SOFR options as an alternative expression (Richard: "probably leave it for now")
- Agentic layer: strategy search, order routing, risk monitor, news on/off switch (discussed 18.09; a possible extension for the write-up)
- RBA decisions via Betfair/Polymarket as a second market pairing (brief v2 "next steps"; revisit after Stage 1)

---

## 3. Current state (24 Sep 2026)

**What exists**

- `code/MarketCap-master/backtester.py`: library of functions (data pulls, ticker parsing, expected-move formulas, per-meeting merge)
- `code/MarketCap-master/test.py`: script that pulls DFF, open and settled Kalshi markets, ZQ front month, candlesticks for all 26 meetings, plots the May 2023 meeting, then loops `pull_and_compare` over all meetings
- `docs/Project Brief.docx` (v2): the method write-up. Section 3.1 explains why v1 (binary probability) was dropped.
- Meeting transcripts for 11.09 and 18.09 in `meetings/` (both partial; the middle of each recording is missing)

**What has been achieved (from the brief)**

- v1 single-outcome method identified as flawed and replaced with the expected-move (bp) framework
- 26 usable settled FOMC meetings reconciled (May 2023 to Jun 2026) across two Kalshi series schemas (legacy `FEDDECISION`, current `KXFEDDECISION`); `FEDDECISION-24JAN` identified as a void listing and excluded
- Ticker parser handles three outcome-label conventions (numeric threshold, literal `>`, and the May 2023 `T` prefix)
- Candlestick pull fetches every outcome contract per meeting, not just the winner
- Retry logic on TradingView

**What has not been done**

- The full 26-meeting run has not completed; there is no spread distribution and no convergence test
- No trade definition, no cost model, no P&L
- No caching; every run re-pulls everything
- No tests, no README, no requirements file; FRED API key is hard-coded in `backtester.py`
- Nathan posted an artefact to the Teams chat after 18.09 that is not in this folder [to be added]

---

## 4. Method and formulas (Stage 1)

Both markets are expressed as the **probability-weighted expected change in the Fed Funds target, in basis points, at one meeting**. Positive = hike, negative = cut.

### 4.1 Futures side (ZQ)

The ZQ contract for the meeting month settles at `100 − (average daily EFFR over that calendar month)`. If the rate is `r0` before the meeting and `r0 + m` after it (in percent), and the decision takes effect from the day after the meeting:

```
implied_avg_rate  = 100 − ZQ_price                       (percent)
w_after           = (days_in_month − meeting_day) / days_in_month
EV_ZQ_bp          = (implied_avg_rate − r0) / w_after × 100
```

`r0` is proxied by the current effective Fed Funds rate (FRED series `DFF`) on each observation date.

**Convention note:** the code currently uses `(days_in_month − meeting_day + 1)`, which counts the meeting day itself as post-decision. CME's settlement uses the daily EFFR, and the new target applies from the day *after* the FOMC announcement, so the correct numerator is `days_in_month − meeting_day`. Fix pending (see section 7).

**Which contract:** the ZQ contract whose delivery month contains the meeting (e.g. `ZQK2023` for the 3 May 2023 meeting). Month codes: F G H J K M N Q U V X Z.

**Caveat:** early in the 60-day window the meeting-month contract may also embed expectations for a *previous* meeting if one falls in the same month or the funds rate is expected to change before the month starts. The window should start after the prior FOMC decision, or `r0` should be the expected rate entering the month rather than today's DFF. To be resolved in Stage 1.

### 4.2 Prediction market side (Kalshi)

Each meeting has one event (`KXFEDDECISION-YYMON`) with mutually exclusive outcome markets (hike 25, hold, cut 25, cut >25, hike >25; occasionally more). Each market's price in dollars is its implied probability.

```
p_i        = (yes_bid_i + yes_ask_i) / 2         (daily close from candlesticks)
EV_K_bp    = Σ_i  p_i × move_i
```

where `move_i` is the bp change the outcome implies (hold = 0, hike 25 = +25, cut 25 = −25).

**Threshold buckets:** outcomes labelled `>25` (coded `-H26`, `-C26`, `-H>25`, `-C>25`, `-TH50`, `-TC50`) mean "25bp or more beyond", i.e. at least 50bp. The parser currently maps these to 25 or 26bp, which understates tail outcomes. Convention to adopt: assign `>25` buckets a representative move of **50bp** (document the choice; sensitivity-test 50 vs 75). Fix pending.

**Liquidity:** a mid computed from a wide or one-sided book is not a price. Rule to adopt: record `spread_i = yes_ask_i − yes_bid_i` and daily volume for every outcome; flag a day as illiquid if any bucket with p > 0.05 has spread > 10c or zero volume; exclude flagged days from signal statistics (keep them in the data).

**Dutch-book check:** for each day, compute `Σ_i yes_ask_i` and `Σ_i yes_bid_i`. If the sum of asks < 1.00 (net of fees) buying every outcome locks in a riskless profit; if the sum of bids > 1.00, selling every outcome does. Richard asked for this. It is a separate, simpler signal and a data-quality check.

### 4.3 The signal

```
spread_bp = EV_ZQ_bp − EV_K_bp
```

Tracked daily over the ~60 days before each meeting. Positive spread = futures more hawkish than Kalshi.

The hypothesis is that Kalshi lags, so `EV_K` moves toward `EV_ZQ`. The tests that matter:

1. Distribution of `spread_bp` by days-to-meeting (mean, sd, percentiles)
2. Convergence: does `|spread_bp|` shrink as days-to-meeting falls?
3. Lead/lag: regress the next-day change in `EV_K` on today's spread, and the next-day change in `EV_ZQ` on today's spread. If Kalshi lags, the first coefficient is positive and significant and the second is ~0. If futures lag (possible around low-volume periods), the hypothesis is reversed and the trade flips.
4. Conditioning: is the spread larger or more persistent in certain regimes (2023 hikes vs 2024 cuts vs 2025-26 holds), or on thin Kalshi days?

### 4.4 The trade (summary; detail in `docs/Trade and Cost Memo.docx`)

- **Convergence trade (primary):** when `spread_bp` exceeds an entry threshold and the day passes the liquidity filter, buy the Kalshi outcome buckets that ZQ implies are underpriced (and/or sell the ones it implies are overpriced), exit when the spread falls inside an exit threshold or at T−1 before the meeting, whichever first. Unhedged; event risk avoided by exiting before the decision.
- **Hedged version (secondary):** same Kalshi leg held to settlement, delta-matched with the opposite position in ZQ so the P&L is the convergence, not the decision.
- **Dutch book (tertiary):** buy or sell the full outcome set when the price sum breaches 1.00 by more than the fee.

---

## 5. Data sources

| Source | Series / endpoint | Access | Notes |
|---|---|---|---|
| FRED (`fredapi`) | `DFF` effective Fed Funds rate, daily | Free, API key | Key must move to `.env` |
| Kalshi public API | `GET /trade-api/v2/historical/markets?series_ticker=KXFEDDECISION&status=settled` (paginated by `cursor`); `GET /historical/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval=1440` | Free, no auth for historical | Base `https://external-api.kalshi.com/trade-api/v2`. Two series schemas: `FEDDECISION-23MAY` … `FEDDECISION-24NOV`, then `KXFEDDECISION-24DEC` onward. `FEDDECISION-24JAN` is void; use `-24JAN31`. |
| TradingView (`tvDatafeed`, unofficial) | `ZQ<month><year>` on `CBOT`, daily OHLC, `n_bars=5000` | Free, unauthenticated, unstable | Drops under looped use. Cache every successful pull. Depth beyond ~2 years unverified against a paid source. |

Candlestick fields used: `end_period_ts`, `yes_bid.close`, `yes_ask.close`, `price.close`, `volume` [confirm field name].

Kalshi fee schedule (July 2026 update): taker `0.07 × C × P × (1−P)`, maker `0.0175 × C × P × (1−P)`, rounded up to the cent; both multipliers = 1 on `KXFEDDECISION`; no settlement fee.

ZQ contract: $5,000,000 notional on one month's interest; quoted `100 − rate`; 1bp = **$41.67**; tick 0.005 ($20.835), 0.0025 in the front month ($10.4175); cash-settled to the monthly average EFFR; last trading day is the last business day of the delivery month; 36 months listed.

---

## 6. Code map

`backtester.py`

| Function | Role | Status |
|---|---|---|
| `parse_outcome_from_ticker` | ticker suffix → (direction, size) | works; threshold-bucket size wrong (see 7) |
| `kalshi_expected_move_bp` | Σ p × move over an event's rows | works, inherits parser issue |
| `parse_meeting_ticker`, `get_futures_symbol` | event ticker → ZQ symbol | works |
| `get_month_params` | meeting day, days in month | works; day-count convention issue (see 7) |
| `zq_expected_move_bp` | ZQ price + DFF → EV in bp | works, same convention issue |
| `implied_probability_from_futures` | v1 binary method | **dead**, keep for the write-up only |
| `get_markets` | live Kalshi markets | used only for the open-markets print |
| `get_candlesticks`, `pull_candlesticks_for_event` | daily candles for every outcome of an event | works, no caching |
| `compute_daily_kalshi_expected_move` | candles → daily EV_K | works |
| `pull_and_compare` | one meeting → merged daily frame with `spread_bp` | works for May 2023; full loop unverified |
| `get_zq_data_with_retry` | TradingView retry wrapper | works, not hardened |
| `get_kalshi_market`, `get_kalshi_probability` | helpers from v1 | unused |

`test.py`: top-to-bottom script, not importable. Contains the 26-meeting list, the May 2023 worked example and plot, and the final loop that builds `historical_kalshi_vs_futures` (a list of frames that is never concatenated or saved).

Environment: Python 3.13/3.14 (both `.pyc` present), `fredapi`, `pandas`, `requests`, `tvDatafeed`, `matplotlib`, `numpy`.

---

## 7. Known issues and shortcomings register

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | `>25bp` threshold buckets mapped to 25/26bp | understates EV_K in tail scenarios | open, fix in Stage 1 |
| 2 | Day-count uses `+1` (counts meeting day as post-decision) | ~3% error in EV_ZQ, larger for late-month meetings | open, fix in Stage 1 |
| 3 | Meeting-month ZQ contract embeds prior-meeting expectations early in the window | spurious spread early in window | open, decide window start rule |
| 4 | Kalshi mids computed from thin or one-sided books | illiquidity read as signal | open, liquidity filter |
| 5 | No transaction costs | cannot say whether signal is tradeable | open, cost memo drafted |
| 6 | TradingView drops connections | runs fail mid-loop | partly mitigated (retry); needs caching |
| 7 | TradingView depth >2y unverified | possible bad early-sample prices | open, spot-check vs CME settlement data |
| 8 | Full run never completed; loop output not saved | no results | open |
| 9 | FRED key in source | hygiene | open, move to `.env` |
| 10 | Duplicate `Project Brief.docx` in `code/` | confusion | remove |
| 11 | Real-time vs revised DFF: DFF is not revised, fine; but "current rate" on any day should be the *target midpoint*, not EFFR, if EFFR drifts within the band | small bias in EV_ZQ | open, decide |
| 12 | Kalshi position limits and depth not measured | capacity unknown | open, record daily volume and book depth |
| 13 | No out-of-sample discipline yet | overfitting risk | open, split rule in DoD |

---

## 8. Decisions log

| Date | Decision | Why |
|---|---|---|
| ~Sep 2026 | Drop v1 binary-probability method; adopt expected-move-in-bp framework | one futures price cannot be decomposed into per-outcome probabilities; breaks on holds |
| 18 Sep | Signal = Kalshi EV vs futures EV; next step is defining the trade | Richard |
| 18 Sep | Park SOFR options | Richard: "probably leave it for now" |
| 18 Sep | Taylor rule / reaction function is the direction after the arb works | Richard |
| 24 Sep | Two-stage plan adopted; Stage 2 waits for Stage 1 DoD | Sean; arb must be solid before extending |
| 24 Sep | System runs in two modes (backtest and live monitor) sharing one codebase; live monitor is part of Stage 1 | Sean; strategy must be operational going forward, not only a backtest |
| 24 Sep | Threshold buckets to be valued at 50bp (sensitivity 50/75) | see issue 1 |
| 24 Sep | Day-count convention: post-decision days = `days − meeting_day` | CME settlement mechanics |
| [TBC] | Deliverable format and submission date | confirm with Richard 25 Sep |

---

## 9. Proposed timeline (to be confirmed once the deadline is known)

| Week of | Milestone |
|---|---|
| 28 Sep | Formula fixes, caching, full 26-meeting run to CSV |
| 5 Oct | Spread distribution, convergence and lead/lag tests, liquidity filter |
| 12 Oct | Trade rules coded, cost model, net P&L backtest with OOS split, live monitor v1 running daily |
| 19 Oct | Stage 1 DoD review with Richard; Stage 2 design note |
| 26 Oct onward | Stage 2 build (Kalshi CPI/unemployment markets → Taylor rule → rule-implied path) |
| [TBC] | Write-up and submission |

---

## 10. Glossary

- **EFFR / DFF**: effective Fed Funds rate; FRED series DFF, daily
- **ZQ**: CME 30-Day Fed Funds futures
- **EV_ZQ, EV_K**: expected move in bp implied by futures and by Kalshi
- **spread_bp**: EV_ZQ − EV_K
- **Bucket / outcome contract**: one Kalshi yes/no market for one decision outcome
- **Threshold bucket**: an outcome of the form ">25bp"
- **Mid**: (yes bid + yes ask)/2
- **Dutch book**: a set of prices on mutually exclusive outcomes that does not sum to 1, allowing a riskless profit
- **DoD**: definition of done
- **WIRP / TAYL**: Bloomberg screens for market-implied policy path and Taylor-rule prescription (Stage 2)

---

## 11. Folder conventions

```
Project/
  PROJECT_CONTEXT.md        this file
  docs/                     briefs, memos, DoD, meeting one-pagers
  code/MarketCap-master/    source; add README, requirements.txt, .env (gitignored), tests/
  data/                     raw/ cached pulls (kalshi/, zq/, fred/), spread_daily.csv, charts/, live/signal_log.csv
  meetings/                 transcripts and notes, named DD.MM meeting.txt
```

Weekly rhythm: Friday meeting with Richard; Sean writes the one-pager Thursday; Nathan posts run outputs to `data/` and the Teams chat.

## 12. Working rules

- Read this file first, then the relevant memo in `docs/`, then the code.
- The method in section 4 is fixed unless the decisions log says otherwise. Propose changes as a new decisions-log row, not by editing section 4 quietly.
- Keep units explicit in code (bp vs percent).
- Anything inferred rather than found in a source is marked in square brackets.
- Update sections 3, 7 and 8 when a piece of work is finished.
