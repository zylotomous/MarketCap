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
import os
import json


fred = Fred(api_key='2fb076f73bbbf80577aa401592ca3110')
tv = TvDatafeed()  # anonymous access works for delayed data on many symbols
BASE = "https://external-api.kalshi.com/trade-api/v2"
endpoint = f"{BASE}/historical/markets?series_ticker=KXFEDDECISION&limit=200&status=settled"

# Disk cache for raw pulls, so a re-run does not hit TradingView/Kalshi again
# and one dropped connection does not lose work already done.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")

CME_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"
}


def get_full_event_outcomes(event_ticker, historical_markets_df):
    """Returns all 5 outcome rows for a given meeting."""
    return historical_markets_df[historical_markets_df["event_ticker"] == event_ticker].copy()

def kalshi_expected_move_bp(event_rows, tail_move_bp=50):
    """
    Computes the probability-weighted expected rate change (in bp)
    implied by Kalshi's full outcome distribution for one meeting.

    Kalshi's tail buckets represent outcomes beyond 25 bp rather than
    an exact move. ``tail_move_bp`` is the representative move assigned
    to those buckets for the expected-value calculation.
    """
    if tail_move_bp <= 25:
        raise ValueError("tail_move_bp must be greater than 25 bp")

    probs, moves = [], []
    for _, row in event_rows.iterrows():
        direction, size = parse_outcome_from_ticker(
            row["ticker"], tail_move_bp=tail_move_bp
        )
        if direction == "hike":
            move = size
        elif direction == "cut":
            move = -size
        else:
            move = 0
        probs.append((float(row["yes_bid_dollars"]) + float(row["yes_ask_dollars"])) / 2)
        moves.append(move)

    # The outcome buckets are mutually exclusive and exhaustive, so the
    # probabilities must sum to 1. Bid/ask mids sum to 1 ± a small spread error;
    # normalizing removes that systematic bias from the expected value.
    probs = np.asarray(probs, dtype=float)
    denom = probs.sum()
    if denom == 0:
        return 0.0
    probs = probs / denom
    return float(np.dot(probs, moves))

def parse_outcome_from_ticker(ticker, tail_move_bp=50):
    """
    Handles all observed Kalshi FOMC ticker suffix conventions:
      -H25, -C25        -> exact bp bucket
      -H26, -C26        -> '>25bp' threshold (numeric-coded convention)
      -H>25, -C>25      -> '>25bp' threshold (literal '>' convention, early 2023 meetings)
      -TH50, -TC50      -> '>Xbp' threshold (May 2023 wide-range convention)
      -H0               -> hold
    """
    if tail_move_bp <= 25:
        raise ValueError("tail_move_bp must be greater than 25 bp")

    match = re.search(r'-(T?)([HC])(>?)(\d+)$', ticker)
    if not match:
        raise ValueError(f"Could not parse outcome from ticker: {ticker}")

    threshold_prefix, letter, threshold_gt, size = match.groups()
    size = int(size)
    is_tail = bool(threshold_prefix or threshold_gt or size == 26)

    if letter == "H" and size == 0:
        direction = "hold"
    elif letter == "H":
        direction = "hike"
    else:
        direction = "cut"

    return direction, tail_move_bp if is_tail else size

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

def get_zq_data_with_retry(symbol, max_retries=3, delay=2, use_cache=True):
    """
    Fetch one ZQ contract's daily history, retrying on failure and caching to
    disk. The fix for the "connection lost / no data" loop: a brand-new
    ``TvDatafeed()`` is created on every attempt. The module-level ``tv`` keeps
    a dead websocket after TradingView drops the connection, so calling
    ``tv.get_hist`` again on the same instance reuses that dead socket and keeps
    failing. A fresh session re-establishes the connection.

    Note: "no data, please check the exchange and symbol" is a *different*
    symptom. If it persists across a fresh session, the symbol really has no
    rows under anonymous access (most likely for an expired contract), not a
    connection problem.
    """
    cache_path = os.path.join(CACHE_DIR, "zq", f"{symbol}.csv")
    if use_cache and os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, index_col=0)
        cached.index = pd.to_datetime(cached.index)
        return cached

    last_err = None
    for attempt in range(max_retries):
        try:
            local_tv = TvDatafeed()
            zq_market = local_tv.get_hist(
                symbol=symbol,
                exchange='CBOT',
                interval=Interval.in_daily,
                n_bars=5000
            )
            if zq_market is not None and not zq_market.empty:
                if use_cache:
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                    zq_market.to_csv(cache_path)
                return zq_market
            last_err = f"empty data for {symbol}"
        except Exception as e:
            last_err = repr(e)
        print(f"Attempt {attempt+1} failed for {symbol} ({last_err}), retrying...")
        time.sleep(delay * (attempt + 1))

    raise ValueError(f"Could not fetch ZQ data for {symbol} after {max_retries} attempts (last: {last_err})")

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

def zq_expected_move_bp(price, current_rate, days_in_month, meeting_day,
                        next_month_price=None):
    """
    Futures-implied EXPECTED rate change (in bp) at the meeting.

    Solving from the meeting-month contract alone,
        EV = (100 - price - current_rate) / weight_after * 100,
    amplifies every measurement error by 1/weight_after, which explodes for
    late-month meetings (small weight_after). For those we use a calendar
    spread against the NEXT-month contract instead, which divides by
    (1 - weight_after) = meeting_day/days_in_month (large when weight_after is
    small):
        EV = ((100 - price_next) - (100 - price)) / (1 - weight_after) * 100.

    This is only valid when the next month contains no meeting (otherwise its
    contract embeds a second decision); the caller passes next_month_price=None
    in that case and we fall back to the meeting-month formula.
    """
    weight_after = (days_in_month - meeting_day) / days_in_month

    if weight_after < 0.5:
        if next_month_price is None:
            if weight_after <= 0:
                return np.nan
            return ((100 - price) - current_rate) / weight_after * 100
        rate_m = 100 - price
        rate_next = 100 - next_month_price
        return (rate_next - rate_m) / (1 - weight_after) * 100

    implied_avg_rate = 100 - price
    return (implied_avg_rate - current_rate) / weight_after * 100


def _safe_cache_name(ticker):
    """Replace characters that are illegal in Windows filenames (e.g. the '>'
    in 'FEDDECISION-23JUN-H>25') so a cache path can be built from any ticker."""
    return re.sub(r'[<>:"/\\|?*]', '_', ticker)


def get_candlesticks(ticker, start_ts, end_ts, period_interval=1440, use_cache=True):
    """
    Kalshi candlestick history for one outcome contract, cached to disk keyed
    by (ticker, start_ts, end_ts) so a re-run is a local read.
    """
    cache_path = os.path.join(CACHE_DIR, "kalshi", f"{_safe_cache_name(ticker)}_{start_ts}_{end_ts}.json")
    if use_cache and os.path.exists(cache_path):
        with open(cache_path) as fh:
            return json.load(fh)

    url = f"{BASE}/historical/markets/{ticker}/candlesticks"
    params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval}
    r = requests.get(url, params=params)
    r.raise_for_status()
    data = r.json()

    if use_cache:
        # A cache-write failure must never discard a successful fetch.
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as fh:
                json.dump(data, fh)
        except Exception as e:
            print(f"Could not cache {ticker}: {e}")
    return data

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

def compute_daily_kalshi_expected_move(candles_df, meeting_name, tail_move_bp=50):
    meeting_candles = candles_df[candles_df["meeting"] == meeting_name].copy()
    meeting_candles["date"] = pd.to_datetime(meeting_candles["end_period_ts"], unit="s", utc=True).dt.normalize().dt.tz_localize(None)

    # rename candle columns to match what kalshi_expected_move_bp expects
    meeting_candles = meeting_candles.rename(columns={
        "yes_bid.close": "yes_bid_dollars",
        "yes_ask.close": "yes_ask_dollars"
    })

    daily_results = []
    for date, group in meeting_candles.groupby("date"):
        move_bp = kalshi_expected_move_bp(group, tail_move_bp=tail_move_bp)
        bid = pd.to_numeric(group["yes_bid_dollars"], errors="coerce")
        ask = pd.to_numeric(group["yes_ask_dollars"], errors="coerce")
        mids = (bid + ask) / 2
        quote_spreads = ask - bid

        liquid_bucket = mids > 0.05
        wide_quote = (quote_spreads > 0.10) & liquid_bucket
        missing_quote = liquid_bucket & (bid.isna() | ask.isna())

        if "volume" in group:
            volume = pd.to_numeric(group["volume"], errors="coerce")
            total_volume = volume.sum(min_count=1)
            zero_volume = liquid_bucket & (volume.fillna(0) <= 0)
        else:
            total_volume = np.nan
            zero_volume = pd.Series(False, index=group.index)

        daily_results.append({
            "date": date,
            "kalshi_expected_move_bp": move_bp,
            "max_quote_spread": quote_spreads[liquid_bucket].max(),
            "total_volume": total_volume,
            "illiquid": bool((wide_quote | missing_quote | zero_volume).any()),
        })

    return pd.DataFrame(daily_results)

def pull_and_compare(meeting_name, dff_df, candles_df, tail_move_bp=50,
                     prev_decision_date=None, meeting_date=None, meeting_months=None):
    """
    prev_decision_date: date of the previous FOMC decision. Observations on or
    before it are dropped: the meeting-month ZQ contract still embeds that
    earlier decision, while DFF has not yet moved, so the spread is spurious.

    meeting_date: the actual decision/settlement date, used for the day-count
    (more robust than inferring it from the last candle). If None, the last
    candle date is used as a fallback.

    meeting_months: optional set of (year, month) tuples that contain an FOMC
    meeting. Used to decide whether the NEXT-month contract is a clean anchor
    for the calendar-spread estimate of late-month meetings (it is not, if the
    next month has a meeting of its own).
    """
    year, month = parse_meeting_ticker(meeting_name)

    zq_market = get_zq_data_with_retry(
        symbol=get_futures_symbol(year, month, root="ZQ"),
        max_retries=3,
        delay=2
    )
    zq_market = zq_market.reset_index()
    zq_market["date"] = pd.to_datetime(zq_market["datetime"]).dt.normalize().dt.tz_localize(None)

    dff_reset = dff_df.reset_index().rename(columns={"index": "date"})

    kalshi_daily = compute_daily_kalshi_expected_move(
        candles_df, meeting_name, tail_move_bp=tail_move_bp
    )
    if prev_decision_date is not None:
        kalshi_daily = kalshi_daily[kalshi_daily["date"] > prev_decision_date].reset_index(drop=True)

    merged_df = pd.merge(kalshi_daily, dff_reset, on="date", how="left")
    merged_df = pd.merge(merged_df, zq_market[["date", "close"]], on="date", how="left")
    merged_df["close"] = merged_df["close"].ffill()
    merged_df["DFF"] = merged_df["DFF"].ffill()

    if meeting_date is None:
        meeting_date = kalshi_daily["date"].iloc[-1]
    meeting_day, days_in_month = get_month_params(meeting_name, meeting_date)

    # For late-month meetings the meeting-month contract's weight_after is
    # small, so its implied move is a noisy 1/weight_after amplification. Anchor
    # on the NEXT-month contract via a calendar spread instead (see
    # zq_expected_move_bp). Only valid if the next month has no meeting.
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    next_has_meeting = (
        meeting_months is not None and (next_year, next_month) in meeting_months
    )
    weight_after = (days_in_month - meeting_day) / days_in_month
    next_month_price = None
    if weight_after < 0.5 and not next_has_meeting:
        try:
            zq_next = get_zq_data_with_retry(
                symbol=get_futures_symbol(next_year, next_month, root="ZQ"),
                max_retries=3,
                delay=2
            )
            zq_next = zq_next.reset_index()
            zq_next["date"] = pd.to_datetime(zq_next["datetime"]).dt.normalize().dt.tz_localize(None)
            merged_df = pd.merge(merged_df, zq_next[["date", "close"]].rename(columns={"close": "close_next"}),
                                 on="date", how="left")
            merged_df["close_next"] = merged_df["close_next"].ffill()
            next_month_price = merged_df["close_next"]
        except Exception as e:
            print(f"Could not fetch next-month ZQ for {meeting_name}: {e}")

    merged_df["zq_expected_move_bp"] = zq_expected_move_bp(
        price=merged_df["close"],
        current_rate=merged_df["DFF"],
        days_in_month=days_in_month,
        meeting_day=meeting_day,
        next_month_price=next_month_price
    )

    merged_df["spread_bp"] = merged_df["zq_expected_move_bp"] - merged_df["kalshi_expected_move_bp"]
    merged_df["meeting"] = meeting_name

    return merged_df
