from fredapi import Fred
import pandas as pd
import requests
from tvDatafeed import TvDatafeed, Interval
import matplotlib.pyplot as plt
import numpy as np
import re
from datetime import datetime
import calendar
import time


fred = Fred(api_key='2fb076f73bbbf80577aa401592ca3110')
tv = TvDatafeed()  # anonymous access works for delayed data on many symbols
BASE = "https://external-api.kalshi.com/trade-api/v2"
endpoint = f"{BASE}/historical/markets?series_ticker=KXFEDDECISION&limit=200&status=settled"

CME_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"
}


def get_full_event_outcomes(event_ticker, historical_markets_df):
    """Returns all 5 outcome rows for a given meeting."""
    return historical_markets_df[historical_markets_df["event_ticker"] == event_ticker].copy()

def kalshi_expected_move_bp(event_rows):
    """
    Computes the probability-weighted expected rate change (in bp)
    implied by Kalshi's full outcome distribution for one meeting.
    """
    total = 0
    for _, row in event_rows.iterrows():
        direction, size = parse_outcome_from_ticker(row["ticker"])
        prob = (float(row["yes_bid_dollars"]) + float(row["yes_ask_dollars"])) / 2
        
        if direction == "hike":
            move = size
        elif direction == "cut":
            move = -size
        else:
            move = 0
        
        total += prob * move
    return total

def parse_outcome_from_ticker(ticker):
    """
    Handles all observed Kalshi FOMC ticker suffix conventions:
      -H25, -C25        -> exact bp bucket
      -H26, -C26        -> '>25bp' threshold (numeric-coded convention)
      -H>25, -C>25      -> '>25bp' threshold (literal '>' convention, early 2023 meetings)
      -TH50, -TC50      -> '>Xbp' threshold (May 2023 wide-range convention)
      -H0               -> hold
    """
    match = re.search(r'-(T?)([HC])(>?)(\d+)$', ticker)
    if not match:
        raise ValueError(f"Could not parse outcome from ticker: {ticker}")

    threshold_prefix, letter, threshold_gt, size = match.groups()
    size = int(size)

    if letter == "H" and size == 0:
        direction = "hold"
    elif letter == "H":
        direction = "hike"
    else:
        direction = "cut"

    return direction, size

def get_futures_symbol(year, month, root="ZQ"):
    code = CME_MONTH_CODES[month]
    return f"{root}{code}{year}"

def parse_meeting_ticker(ticker):
    match = re.search(r'(\d{2})([A-Z]{3})', ticker)
    yy, mon_abbr = match.groups()
    year = 2000 + int(yy)
    month = datetime.strptime(mon_abbr, "%b").month
    return year, month

def get_month_params(ticker, meeting_date):
    year, month = parse_meeting_ticker(ticker)
    days_in_month = calendar.monthrange(year, month)[1]
    meeting_day = meeting_date.day
    return meeting_day, days_in_month

def get_markets(series_ticker, status=None):
    params = {"series_ticker": series_ticker, "limit": 200}
    if status:
        params["status"] = status  # "open", "closed", "settled"
    r = requests.get(f"{BASE}/markets", params=params)
    r.raise_for_status()
    return r.json()["markets"]

def get_kalshi_market(event_ticker, kalshi_df):
    market = kalshi_df[(kalshi_df["event_ticker"] == event_ticker)].reset_index(drop = True)

    print(market[["ticker", "subtitle", "close_time", "yes_bid_dollars", "yes_ask_dollars"]])

    return market

def get_zq_data_with_retry(symbol, max_retries=3, delay=2):
    for attempt in range(max_retries):
        zq_market = tv.get_hist(
            symbol=symbol,
            exchange='CBOT',
            interval=Interval.in_daily,
            n_bars=5000
        )
        if zq_market is not None and not zq_market.empty:
            return zq_market
        print(f"Attempt {attempt+1} failed for {symbol}, retrying...")
        time.sleep(delay)
    raise ValueError(f"Could not fetch ZQ data for {symbol} after {max_retries} attempts")

def get_kalshi_probability(kalshi_market):
    yes_bid = kalshi_market["yes_bid_dollars"].astype(float)
    yes_ask = kalshi_market["yes_ask_dollars"].astype(float)

    if yes_bid is not None and yes_ask is not None:
        probability = (yes_bid + yes_ask) / 2

        kalshi_market["probability"] = probability

        return kalshi_market[["title", "probability"]]
    
    else:
        return None

def implied_probability_from_futures(price, current_rate, move_bp, days_in_month, meeting_day):
    implied_average_rate = 100 - price

    weight_after = (days_in_month - meeting_day + 1) / days_in_month

    p_hike = (implied_average_rate - current_rate) / (move_bp * weight_after)

    print(p_hike)

    return p_hike

def zq_expected_move_bp(price, current_rate, days_in_month, meeting_day):
    """
    Solves directly for the futures-implied EXPECTED rate change (in bp),
    no assumed move size needed. Works uniformly for hikes, cuts, and holds.
    """
    implied_avg_rate = 100 - price
    weight_after = (days_in_month - meeting_day + 1) / days_in_month
    expected_move_bp = (implied_avg_rate - current_rate) / weight_after * 100
    return expected_move_bp


def get_candlesticks(ticker, start_ts, end_ts, period_interval=1440):
    url = f"{BASE}/historical/markets/{ticker}/candlesticks"
    params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval}
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()

def pull_candlesticks_for_event(event_ticker, close_time, lookback_days=60, historical_markets_df=None):
    """
    Pulls candlestick history for ALL 5 outcome contracts of a given meeting,
    not just the winning one.
    """
    rows = historical_markets_df[historical_markets_df["event_ticker"] == event_ticker]

    end_ts = int(close_time.timestamp())
    start_ts = end_ts - lookback_days * 86400

    all_dfs = []
    for _, row in rows.iterrows():
        ticker = row["ticker"]
        try:
            candles = get_candlesticks(ticker, start_ts, end_ts)
            df_temp = pd.json_normalize(candles["candlesticks"])
            df_temp["ticker"] = ticker
            df_temp["meeting"] = event_ticker
            all_dfs.append(df_temp)
        except Exception as e:
            print(f"Failed on {ticker}: {e}")

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    else:
        return pd.DataFrame()

# assume that we are reading in the raw, unprocessed historical markets
# from tradingview and fred, meaning we need to do some data processing in
# this pull and compare function itself 

def compute_daily_kalshi_expected_move(candles_df, meeting_name):
    meeting_candles = candles_df[candles_df["meeting"] == meeting_name].copy()
    meeting_candles["date"] = pd.to_datetime(meeting_candles["end_period_ts"], unit="s", utc=True).dt.normalize().dt.tz_localize(None)

    # rename candle columns to match what kalshi_expected_move_bp expects
    meeting_candles = meeting_candles.rename(columns={
        "yes_bid.close": "yes_bid_dollars",
        "yes_ask.close": "yes_ask_dollars"
    })

    daily_results = []
    for date, group in meeting_candles.groupby("date"):
        move_bp = kalshi_expected_move_bp(group)
        daily_results.append({"date": date, "kalshi_expected_move_bp": move_bp})

    return pd.DataFrame(daily_results)

def pull_and_compare(meeting_name, dff_df, candles_df):
    year, month = parse_meeting_ticker(meeting_name)

    zq_market = get_zq_data_with_retry(
        symbol=get_futures_symbol(year, month, root="ZQ"),
        max_retries=3,
        delay=2
    )
    zq_market = zq_market.reset_index()
    zq_market["date"] = pd.to_datetime(zq_market["datetime"]).dt.normalize().dt.tz_localize(None)

    dff_reset = dff_df.reset_index().rename(columns={"index": "date"})

    kalshi_daily = compute_daily_kalshi_expected_move(candles_df, meeting_name)

    merged_df = pd.merge(kalshi_daily, dff_reset, on="date", how="left")
    merged_df = pd.merge(merged_df, zq_market[["date", "close"]], on="date", how="left")
    merged_df["close"] = merged_df["close"].ffill()

    meeting_day, days_in_month = get_month_params(meeting_name, kalshi_daily["date"].iloc[-1])

    merged_df["zq_expected_move_bp"] = zq_expected_move_bp(
        price=merged_df["close"],
        current_rate=merged_df["DFF"],
        days_in_month=days_in_month,
        meeting_day=meeting_day
    )

    merged_df["spread_bp"] = merged_df["zq_expected_move_bp"] - merged_df["kalshi_expected_move_bp"]

    return merged_df