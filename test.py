import time

from backtester import *

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

meeting_summary = winners.rename(columns={
    "event_ticker": "meeting",
    "winning_ticker": "ticker",
    "close_time": "meeting_date",
    "yes_sub_title": "actual_outcome"
})[["meeting", "meeting_date", "actual_outcome", "ticker"]]


# loop through all 27 meetings
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

"""
A list of all the fed decision rates
Pulling: FEDDECISION-23MAY
Pulling: FEDDECISION-23JUN
Pulling: FEDDECISION-23JUL
Pulling: FEDDECISION-23SEP
Pulling: FEDDECISION-23NOV
Pulling: FEDDECISION-23DEC
Pulling: FEDDECISION-24JAN
Pulling: FEDDECISION-24JAN31
Pulling: FEDDECISION-24MAR20
Pulling: FEDDECISION-24MAY
Pulling: FEDDECISION-24JUN
Pulling: FEDDECISION-24JUL
Pulling: FEDDECISION-24SEP
Pulling: FEDDECISION-24NOV
Pulling: KXFEDDECISION-24DEC
Pulling: KXFEDDECISION-25JAN
Pulling: KXFEDDECISION-25MAR
Pulling: KXFEDDECISION-25MAY
Pulling: KXFEDDECISION-25JUN
Pulling: KXFEDDECISION-25JUL
Pulling: KXFEDDECISION-25SEP
Pulling: KXFEDDECISION-25OCT
Pulling: KXFEDDECISION-25DEC
Pulling: KXFEDDECISION-26JAN
Pulling: KXFEDDECISION-26MAR
Pulling: KXFEDDECISION-26APR
Pulling: KXFEDDECISION-26JUN """

# 24Jan seems to be a bug, real one should be 24JAN31
meeting_tickers = meeting_summary[meeting_summary["meeting"] != "FEDDECISION-24JAN"]["meeting"].tolist()

historical_kalshi_vs_futures = []
for meeting in meeting_tickers:
    print("Pulling:", meeting)
    historical_kalshi_vs_futures.append(pull_and_compare(
        meeting_name=meeting,
        dff_df=dff_df,
        candles_df=candles_df
    ))


print("All meetintgs pulled")

historical_kalshi_vs_futures_df = pd.concat(historical_kalshi_vs_futures, ignore_index=True)

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