import time
import importlib
import os
import sys

# The Windows console is cp1252, which cannot encode the U+2212 "−" used in
# several print() strings below. That crashed the run at the first such print
# and hid every result. Force UTF-8 so the script runs to completion.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import backtester
importlib.reload(backtester)
from backtester import *

TAIL_MOVE_BP = 50

dff = fred.get_series('DFF')
print(dff.tail())

current_rate = dff.iloc[-1]
print(f"Most recent DFF: {current_rate}%")

dff = pd.DataFrame(dff)

dff_df = dff.rename(columns={0: 'DFF'})

# Fed decision markets
fed_markets = get_markets("KXFEDDECISION", status="open")
for m in fed_markets:
    print(m["ticker"], "|", m["title"], "|", m.get("yes_bid"), "/", m.get("yes_ask"),
          "| expires:", m.get("expiration_time"))

fed_markets_df = pd.DataFrame(fed_markets)

datetime_cols = ["close_time", "created_time", "expected_expiration_time",
                  "expiration_time", "updated_time"]

for col in datetime_cols:
    fed_markets_df[col] = pd.to_datetime(fed_markets_df[col], utc=True)

print(fed_markets_df.dtypes[datetime_cols])

# Fed Funds futures, front month example
fff = tv.get_hist(symbol='ZQ1!', exchange='CBOT', interval=Interval.in_daily, n_bars=90)
print(fff)

fff = pd.DataFrame(fff)

""" Extracting previously settled markets"""

historical_markets = []
cursor = None

while True:
    request_url = f"{endpoint}&cursor={cursor}" if cursor else endpoint

    # Just call it directly, no headers required
    response = requests.get(request_url).json()

    historical_markets.extend(response.get('markets', []))
    cursor = response.get('cursor')

    if not cursor:
        break

historical_markets_df = pd.DataFrame(historical_markets)

datetime_cols = ["close_time", "created_time", "expected_expiration_time",
                  "expiration_time", "updated_time"]

for col in datetime_cols:
    historical_markets_df[col] = pd.to_datetime(historical_markets_df[col], utc=True)

# Extract the winning bets for each settled market
winners = historical_markets_df[historical_markets_df["result"] == "yes"][
    ["event_ticker", "close_time", "yes_sub_title", "settlement_value_dollars", "ticker"]
].sort_values("close_time").reset_index(drop=True)

print(winners)
print(len(winners), "meetings")

# NOTE: the old rename listed "winning_ticker" as a source column, but that
# column does not exist in `winners` (it is already called "ticker"), so the
# rename was a silent no-op. Removed it.
meeting_summary = winners.rename(columns={
    "event_ticker": "meeting",
    "close_time": "meeting_date", Pook the opportunities when they had them and kept their mental in check, playing out the back half much more cleanly. Yahoo was solid from start to finish, especially stepping up in game five, and Clisp also bounced back well, playing everything from the last team fight in game two all the way to the end of the series. 

As for C Nine, while they did throw games and they did lose, I came away from the series feeling like they played closer to how they did in playoffs than their extremely underwhelming regular season. If they keep this exact form, I would favor them in the Lord Rackle to get to the qualification series. 

It's pretty disappointing for it to go like this, but I think every player reached closer to their ceiling at least once over the course of the series with the EU versus.
    "yes_sub_title": "actual_outcome",
})[["meeting", "meeting_date", "actual_outcome", "ticker"]]


# Loop through all settled meetings. Candlesticks are cached to disk inside
# backtester.get_candlesticks, so re-runs are fast after the first pull.
all_candles = []

for _, m in meeting_summary.iterrows():
    print("Pulling:", m["meeting"])
    try:
        result_df = pull_candlesticks_for_event(
            event_ticker=m["meeting"],
            close_time=m["meeting_date"],
            lookback_days=60,
            historical_markets_df=historical_markets_df
        )
        if not result_df.empty:
            all_candles.append(result_df)
        time.sleep(0.3)
    except Exception as e:
        print("Failed:", m["meeting"], "-", e)

candles_df = pd.concat(all_candles, ignore_index=True)
print(candles_df.head())
print(candles_df.columns.tolist())

candles_df["date"] = pd.to_datetime(candles_df["end_period_ts"], unit="s", utc=True)
print(candles_df[["meeting", "date", "price.close"]].head())

# 24Jan seems to be a bug, real one should be 24JAN31
meeting_tickers = meeting_summary[meeting_summary["meeting"] != "FEDDECISION-24JAN"]["meeting"].tolist()

# Previous decision date for each meeting, so the window starts after it
# (avoids the prior decision leaking into the meeting-month ZQ contract)
decision_dates = (
    meeting_summary[meeting_summary["meeting"].isin(meeting_tickers)]
    .assign(decision_date=lambda d: pd.to_datetime(d["meeting_date"], utc=True)
            .dt.tz_localize(None).dt.normalize())
    .sort_values("decision_date")
    .reset_index(drop=True)
)
decision_dates["prev_decision_date"] = decision_dates["decision_date"].shift(1)
prev_decision = dict(zip(decision_dates["meeting"], decision_dates["prev_decision_date"]))

# (year, month) of every meeting, so pull_and_compare can tell whether the
# next-month contract is a clean calendar-spread anchor (next month has no
# meeting) or would embed a second decision.
meeting_months = set(
    (parse_meeting_ticker(t)[0], parse_meeting_ticker(t)[1])
    for t in meeting_tickers
)
# Actual decision/settlement date per meeting, tz-naive, for a robust day-count.
meeting_date_map = dict(zip(
    meeting_summary["meeting"],
    pd.to_datetime(meeting_summary["meeting_date"], utc=True).dt.tz_localize(None)
))

# Build the merged daily frame. Each meeting is independent, so one failed
# TradingView pull no longer aborts the whole run: it is logged and skipped.
historical_kalshi_vs_futures = []
errors = []
for meeting in meeting_tickers:
    print("Pulling:", meeting)
    prev_date = prev_decision[meeting]
    try:
        historical_kalshi_vs_futures.append(pull_and_compare(
            meeting_name=meeting,
            dff_df=dff_df,
            candles_df=candles_df,
            tail_move_bp=TAIL_MOVE_BP,
            prev_decision_date=None if pd.isna(prev_date) else prev_date,
            meeting_date=meeting_date_map.get(meeting),
            meeting_months=meeting_months,
        ))
    except Exception as e:
        errors.append((meeting, repr(e)))
        print(f"FAILED {meeting}: {e}")

print("All meetings pulled")
if errors:
    print("Errors encountered:")
    for meeting, err in errors:
        print(f"  {meeting}: {err}")

historical_kalshi_vs_futures_df = pd.concat(historical_kalshi_vs_futures, ignore_index=True)

# Persist the run so the analysis below can be re-run without re-pulling.
os.makedirs("data", exist_ok=True)
historical_kalshi_vs_futures_df.to_csv("data/spread_daily.csv", index=False)
print("Saved data/spread_daily.csv:", historical_kalshi_vs_futures_df.shape)

# ── 1. Spread over time, aligned by days-before-meeting ──────────────────────
meeting_dates = (
    historical_kalshi_vs_futures_df
    .groupby("meeting")["date"]
    .max()
    .rename("meeting_date")
)
df = historical_kalshi_vs_futures_df.join(meeting_dates, on="meeting")
df["days_before"] = (df["meeting_date"] - df["date"]).dt.days

fig, ax = plt.subplots(figsize=(12, 5))
for meeting, grp in df.groupby("meeting"):
    grp_sorted = grp.sort_values("days_before", ascending=False)
    ax.plot(grp_sorted["days_before"], grp_sorted["spread_bp"],
            alpha=0.6, linewidth=1, label=meeting)
ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
ax.invert_xaxis()
ax.set_xlabel("Days before meeting")
ax.set_ylabel("Spread (bp)  [ZQ − Kalshi]")
ax.set_title("ZQ vs Kalshi expected move spread — all meetings")
ax.legend(fontsize=6, ncol=3, loc="upper left")
plt.tight_layout()
plt.show()

# ── 2. Average spread per meeting ─────────────────────────────────────────────
avg_spread = (
    historical_kalshi_vs_futures_df
    .groupby("meeting")["spread_bp"]
    .mean()
    .sort_values()
)
print("\nAverage spread (ZQ − Kalshi) by meeting:")
print(avg_spread.to_string())

fig, ax = plt.subplots(figsize=(10, 5))
avg_spread.plot(kind="bar", ax=ax, color=["#d62728" if v < 0 else "#1f77b4" for v in avg_spread])
ax.axhline(0, color="black", linewidth=0.8)
ax.set_ylabel("Avg spread (bp)")
ax.set_title("Average ZQ − Kalshi spread by meeting")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.show()

# ── 3. Does spread converge near the meeting? ─────────────────────────────────
spread_by_days = df.groupby("days_before")["spread_bp"].mean()
fig, ax = plt.subplots(figsize=(10, 4))
spread_by_days.sort_index(ascending=False).plot(ax=ax)
ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
ax.invert_xaxis()
ax.set_xlabel("Days before meeting")
ax.set_ylabel("Avg spread (bp)")
ax.set_title("Average spread convergence across all meetings")
plt.tight_layout()
plt.show()

# ── 4. Cross-correlation: does Kalshi lead or lag futures? ────────────────────
lags, corrs = [], []
for meeting, grp in df.groupby("meeting"):
    grp = grp.sort_values("date")
    dk = grp["kalshi_expected_move_bp"].diff().dropna()
    dz = grp["zq_expected_move_bp"].diff().dropna()
    idx = dk.index.intersection(dz.index)
    if len(idx) < 10:
        continue
    for lag in range(-5, 6):
        shifted = dz.shift(lag).reindex(idx)
        valid = dk.reindex(idx).notna() & shifted.notna()
        if valid.sum() < 5:
            continue
        c = dk.reindex(idx)[valid].corr(shifted[valid])
        lags.append(lag)
        corrs.append(c)

lag_df = pd.DataFrame({"lag": lags, "corr": corrs}).groupby("lag")["corr"].mean()
fig, ax = plt.subplots(figsize=(8, 4))
lag_df.plot(kind="bar", ax=ax)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xlabel("Lag (days, positive = ZQ leads Kalshi)")
ax.set_ylabel("Avg cross-correlation")
ax.set_title("Cross-correlation: daily changes in ZQ vs Kalshi expected move")
plt.tight_layout()
plt.show()

# ── 5. Robustness, predictive tests, and a convergence backtest ───────────────
# (a) tail-value sensitivity, (b) lead/lag, (c) a non-overlapping, costed
# convergence backtest.

# Values of the representative move (bp) assigned to the ">25bp" Kalshi buckets
TAIL_SENSITIVITIES = [50, 75, 100]
# Look-back windows in days before the meeting, for the spread-by-window table
WINDOWS = [60, 35, 21, 14]
# Entry rule: only trade when |spread| is bigger than this many bp
ENTRY_THRESHOLDS_BP = [1, 2, 3, 5]
# Exit rule: leave as soon as |spread| falls to this level or below
EXIT_THRESHOLD_BP = 0.5
# Exit rule: otherwise leave after at most this many trading rows
MAX_HOLD_DAYS = 5
# Round-trip cost per trade, in bp of expected move. Kalshi taker ≈ 0.07·P·(1−P)
# per side; on a 50c contract that is ≈3.5c round trip ≈ ~1.4bp of EV, before
# the ZQ leg. This replaces the old 0.5bp placeholder.
COST_PER_TRADE_BP = 1.4


def revalue_with_tail_assumption(base_df, candles, meeting_names, tail_move_bp):
    """
    Recompute the spread under a different tail-bucket value (e.g. 75bp).

    Only the Kalshi side depends on the tail value, so the Kalshi expected
    move is rebuilt from the cached candles and joined to the ZQ column that
    is already in base_df. No extra TradingView calls are needed.
    """
    frames = []
    for meeting in meeting_names:
        kalshi = compute_daily_kalshi_expected_move(
            candles, meeting, tail_move_bp=tail_move_bp
        )
        kalshi["meeting"] = meeting
        zq = base_df[base_df["meeting"] == meeting][[
            "meeting", "date", "zq_expected_move_bp", "days_before"
        ]]
        frames.append(pd.merge(kalshi, zq, on=["meeting", "date"], how="inner"))

    result = pd.concat(frames, ignore_index=True)
    result["spread_bp"] = (
        result["zq_expected_move_bp"]
        - result["kalshi_expected_move_bp"]
    )
    return result


def ols_summary(frame, target_column, feature_column="spread_bp"):
    """
    Simple regression: target = intercept + beta * spread, solved by least
    squares. Returns sample size, beta and R-squared (no standard errors).
    """
    sample = frame[[feature_column, target_column]].dropna()
    if len(sample) < 3:
        return {"n": len(sample), "beta": np.nan, "r2": np.nan}

    x = sample[feature_column].to_numpy(dtype=float)
    y = sample[target_column].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    coefficients, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficients
    total_ss = np.sum((y - y.mean()) ** 2)
    residual_ss = np.sum((y - fitted) ** 2)
    r2 = np.nan if total_ss == 0 else 1 - residual_ss / total_ss
    return {"n": int(len(sample)), "beta": float(coefficients[1]), "r2": float(r2)}


def ols_with_se(frame, target_column, feature_column):
    """
    Single-feature OLS that also returns the standard error and t-stat of the
    slope, so a coefficient can actually be called significant. |t| > ~2 is
    roughly the 5% level for the sample sizes here.
    """
    sample = frame[[feature_column, target_column]].dropna()
    if len(sample) < 3:
        return {"n": int(len(sample)), "beta": np.nan, "se": np.nan, "t": np.nan, "r2": np.nan}

    x = sample[feature_column].to_numpy(dtype=float)
    y = sample[target_column].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    sigma2 = float((resid @ resid) / dof)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = beta / se
    total_ss = np.sum((y - y.mean()) ** 2)
    r2 = np.nan if total_ss == 0 else 1 - (resid @ resid) / total_ss
    return {
        "n": int(len(sample)),
        "beta": float(beta[1]),
        "se": float(se[1]),
        "t": float(t[1]),
        "r2": float(r2),
    }


def granger_lead_lag(frame):
    """
    Cleaner lead/lag test than regressing a *change* on the *level* spread.

    Regressing K_{t+1}-K_t on (Z_t - K_t) shares the -K_t term between the two
    sides, which mechanically inflates the Kalshi coefficient (and deflates the
    ZQ one). The change-on-change form has no shared level term:

        ZQ leads Kalshi   :  K_{t+1}-K_t  ~  Z_t - Z_{t-1}
        Kalshi leads ZQ   :  Z_{t+1}-Z_t  ~  K_t - K_{t-1}
    """
    g = frame.sort_values(["meeting", "date"]).copy()
    g["dK"] = g.groupby("meeting")["kalshi_expected_move_bp"].diff()
    g["dZ"] = g.groupby("meeting")["zq_expected_move_bp"].diff()
    g["dK_next"] = g.groupby("meeting")["dK"].shift(-1)
    g["dZ_next"] = g.groupby("meeting")["dZ"].shift(-1)
    z_leads_k = ols_with_se(g, "dK_next", "dZ")
    k_leads_z = ols_with_se(g, "dZ_next", "dK")
    return z_leads_k, k_leads_z


def multivariate_ols_summary(frame, target_column, feature_columns):
    """
    OLS with several features (here spread and log_volume). Returns intercept,
    one coefficient per feature, and R-squared.
    """
    sample = frame[[*feature_columns, target_column]].dropna()
    if len(sample) <= len(feature_columns) + 1:
        return {"n": int(len(sample)), "coefficients": {}, "r2": None}

    x = sample[list(feature_columns)].to_numpy(dtype=float)
    y = sample[target_column].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    coefficients, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficients
    total_ss = np.sum((y - y.mean()) ** 2)
    residual_ss = np.sum((y - fitted) ** 2)
    r2 = None if total_ss == 0 else float(1 - residual_ss / total_ss)
    return {
        "n": int(len(sample)),
        "coefficients": {
            "intercept": float(coefficients[0]),
            **{
                name: float(value)
                for name, value in zip(feature_columns, coefficients[1:])
            },
        },
        "r2": r2,
    }


def add_predictive_columns(frame):
    """
    Add the columns the regressions need:
      kalshi_change_next / zq_change_next : tomorrow's change in each market's
          expected move (bp), computed within a meeting so it never crosses
          from one meeting into the next. The last day of each meeting is NaN.
      log_volume : log(1 + total Kalshi volume that day), a liquidity control.
    """
    if "total_volume" not in frame.columns:
        raise ValueError(
            "df does not contain total_volume. Rerun test.py from the top so "
            "volume diagnostics are rebuilt."
        )

    result = frame.sort_values(["meeting", "date"]).copy()
    result["kalshi_change_next"] = (
        result.groupby("meeting")["kalshi_expected_move_bp"].shift(-1)
        - result["kalshi_expected_move_bp"]
    )
    result["zq_change_next"] = (
        result.groupby("meeting")["zq_expected_move_bp"].shift(-1)
        - result["zq_expected_move_bp"]
    )
    result["log_volume"] = np.log1p(
        pd.to_numeric(result["total_volume"], errors="coerce").clip(lower=0)
    )
    return result


def backtest_convergence(frame, entry_threshold_bp, cost_bp=COST_PER_TRADE_BP,
                         exit_threshold_bp=EXIT_THRESHOLD_BP,
                         max_hold_days=MAX_HOLD_DAYS):
    """
    Non-overlapping convergence backtest. Unlike the old simulate_convergence,
    at most one position is open per meeting at a time, and each trade pays the
    full round-trip cost. Still a mid-price proxy (no fills, no position size,
    no dollar P&L), but it no longer double-counts by letting every wide day be
    its own overlapping "trade".

    gross = |spread at entry| - |spread at exit|   (positive = narrowed)
    net   = gross - cost_bp

    Caveat: entering when |spread| is wide tends to select noise, and noise
    reverts, so a high win rate is expected even with no real edge.
    """
    trades = []
    for meeting, group in frame.groupby("meeting"):
        group = group.sort_values("date").reset_index(drop=True)
        in_position = False
        entry = None
        for _, row in group.iterrows():
            if bool(row.get("illiquid", False)):
                continue
            if not in_position:
                if (abs(row["spread_bp"]) >= entry_threshold_bp
                        and 14 <= row["days_before"] <= 60):
                    entry = row
                    in_position = True
            else:
                held = (row["date"] - entry["date"]).days
                if (abs(row["spread_bp"]) <= exit_threshold_bp
                        or row["days_before"] <= 1
                        or held >= max_hold_days):
                    gross = abs(entry["spread_bp"]) - abs(row["spread_bp"])
                    trades.append({
                        "meeting": meeting,
                        "entry_date": entry["date"],
                        "exit_date": row["date"],
                        "entry_spread_bp": entry["spread_bp"],
                        "exit_spread_bp": row["spread_bp"],
                        "gross_bp": gross,
                        "net_bp": gross - cost_bp,
                    })
                    in_position = False
                    entry = None
    return pd.DataFrame(trades)


# Decision date per meeting, for a chronological train/OOS split at the meeting
# level (train = 2023-2025, out-of-sample = 2026 onwards).
meeting_dates_for_split = meeting_summary[["meeting", "meeting_date"]].copy()
meeting_dates_for_split = meeting_dates_for_split.rename(
    columns={"meeting_date": "decision_date"}
)
meeting_dates_for_split["decision_date"] = pd.to_datetime(
    meeting_dates_for_split["decision_date"], utc=True
).dt.tz_localize(None)

# (a) Does the average spread change with the tail assumption?
print("\nTail-value sensitivity:")
sensitivity_frames = {}
for tail_move_bp in TAIL_SENSITIVITIES:
    sensitivity = revalue_with_tail_assumption(
        df, candles_df, meeting_tickers, tail_move_bp
    )
    sensitivity_frames[tail_move_bp] = sensitivity
    print({
        "tail_move_bp": tail_move_bp,
        "mean_spread_bp": float(sensitivity["spread_bp"].mean()),
        "median_spread_bp": float(sensitivity["spread_bp"].median()),
        "meeting_count": int(sensitivity["meeting"].nunique()),
    })

# (a) Spread size in the last N days only. If mean |spread| falls as the window
# shrinks, the spread is converging into the meeting.
print("\nSpread by lookback window:")
for window in WINDOWS:
    window_sample = df[df["days_before"].between(1, window)]
    print({
        "window_days": window,
        "observations": int(len(window_sample)),
        "mean_spread_bp": float(window_sample["spread_bp"].mean()),
        "mean_abs_spread_bp": float(window_sample["spread_bp"].abs().mean()),
    })

# (b) Lead/lag. The clean change-on-change test first.
z_leads_k, k_leads_z = granger_lead_lag(df)
print("\nGranger lead/lag (change-on-change, no shared level term):")
print("  ZQ -> Kalshi (beta > 0 if Kalshi lags):", z_leads_k)
print("  Kalshi -> ZQ (beta ~ 0):              ", k_leads_z)

# (b) The original level-on-change regressions, kept for continuity. NOTE: the
# beta is mechanically inflated (Kalshi) / deflated (ZQ) by the shared -K_t
# term — see granger_lead_lag for the clean version.
predictive = add_predictive_columns(df)
print("\nPooled predictive regressions (level spread -> next change; biased):")
for target in ["kalshi_change_next", "zq_change_next"]:
    print(target, ols_summary(predictive, target))

predictive = predictive.merge(meeting_dates_for_split, on="meeting", how="left")
predictor_columns = ["spread_bp", "log_volume"]
print("\nPooled multivariate regressions: target_next ~ spread_today + log_volume")
for target in ["kalshi_change_next", "zq_change_next"]:
    print(target, multivariate_ols_summary(
        predictive, target, predictor_columns
    ))

# Same regressions on train meetings (2023-2025) and held-out meetings (2026).
train = predictive[predictive["decision_date"] < pd.Timestamp("2026-01-01")]
test = predictive[predictive["decision_date"] >= pd.Timestamp("2026-01-01")]
print("\nChronological train/OOS regressions (train 2023-2025, OOS 2026):")
for label, sample in [("train_2023_2025", train), ("oos_2026", test)]:
    for target in ["kalshi_change_next", "zq_change_next"]:
        print(label, target, ols_summary(sample, target))
        print(label, target, multivariate_ols_summary(
            sample, target, predictor_columns
        ))

# (c) Non-overlapping, costed convergence backtest.
print("\nConvergence backtest (non-overlapping, cost =", COST_PER_TRADE_BP, "bp/trade):")
for threshold in ENTRY_THRESHOLDS_BP:
    trades = backtest_convergence(df, threshold)
    print({
        "entry_threshold_bp": threshold,
        "trades": int(len(trades)),
        "mean_gross_bp": float(trades["gross_bp"].mean()) if not trades.empty else None,
        "mean_net_bp": float(trades["net_bp"].mean()) if not trades.empty else None,
        "total_net_bp": float(trades["net_bp"].sum()) if not trades.empty else 0.0,
        "win_rate": float((trades["net_bp"] > 0).mean()) if not trades.empty else None,
    })
