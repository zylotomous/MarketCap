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

""" Extracting may 23 decision - Hike 25bp"""

may23_market = candles_df[candles_df["meeting"] == "FEDDECISION-23MAY"].reset_index(drop=True)

may23_market["date"] = pd.to_datetime(may23_market["date"]).dt.normalize().dt.tz_localize(None)

dff_may23 = dff_df.reset_index().rename(columns={"index": "date"})

zq_may23 = tv.get_hist(
    symbol='ZQK2023',
    exchange='CBOT',
    interval=Interval.in_daily,
    n_bars=5000  # go back far enough to guarantee coverage of a 2023 date
)

zq_may23 = zq_may23.reset_index()

zq_may23["date"] = pd.to_datetime(zq_may23["datetime"]).dt.normalize().dt.tz_localize(None)

may23_merged = pd.merge(may23_market, dff_may23, on = "date", how = "left")
may23_merged = pd.merge(may23_merged, zq_may23[["date", "close"]], on = "date", how = "left")
may23_merged["close"] = may23_merged["close"].ffill()
may23_merged["implied_prob"] = implied_probability_from_futures(
    price=may23_merged["close"],
    current_rate=may23_merged["DFF"],
    move_bp=0.25,
    days_in_month=31,
    meeting_day=3
)
may23_merged["kalshi_prob"] = (may23_merged["yes_ask.close"].astype(float) + may23_merged["yes_bid.close"].astype(float)) / 2


fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(may23_merged["date"], may23_merged["kalshi_prob"], label="Kalshi probability", marker="o", markersize=3)
ax.plot(may23_merged["date"], may23_merged["implied_prob"], label="ZQ implied probability", marker="o", markersize=3)

ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8)
ax.axhline(0.0, color="gray", linestyle="--", linewidth=0.8)

ax.set_xlabel("Date")
ax.set_ylabel("Implied probability")
ax.set_title("Kalshi vs ZQ implied probability — May 2023 FOMC meeting")
ax.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

may23_test = pull_and_compare(
    meeting_name="FEDDECISION-23MAY",
    dff_df=dff_df,
    candles_df=candles_df)


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
