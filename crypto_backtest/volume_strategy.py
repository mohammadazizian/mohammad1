#!/usr/bin/env python3
"""
Volume-Delta Burst  --  BTC / ETH, 1H candles, fixed SL / TP on every trade
===========================================================================

Trigger (volume only)
    delta      = taker-buy volume - taker-sell volume of each 1H bar
    burst      = sum of delta over the last 2 bars
    z          = (burst - mean(burst, 336 bars)) / std(burst, 336 bars)
    LONG   when z crosses above +2.5   (abnormal aggressive buying)
    SHORT  when z crosses below -2.5   (abnormal aggressive selling)

Trade management (set once, at entry, never moved)
    stop loss   = entry -/+ 6.0 x ATR(24)      stop-market
    take profit = entry +/- 4.0 x ATR(24)      resting limit
    ATR is the value of the last closed bar. There is no other exit: no time stop,
    no trailing, no signal exit. One position per asset; signals are ignored while in a trade.

Monthly entry lock
    Once the mark-to-market month-to-date PnL reaches +1.0% (and at least one trade was opened
    that month) no NEW trade is opened until the next calendar month. Open trades are left
    alone and still end only at their fixed SL or TP.

Execution model
    signal on a closed bar -> market order at the next bar's open
    entry and stop-loss fills: taker 0.04% + 0.02% slippage
    take-profit fills: maker 0.01%, only if price trades 1 bp THROUGH the level, never on the entry bar
    if SL and TP are both inside one bar, the SL is assumed to be hit first
    fixed 1x notional per asset, no leverage, no compounding; monthly PnL is mark-to-market

    python volume_strategy.py --out results_volume
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

PARAMS = dict(
    delta_bars=2, z_len=336, z_k=2.5,
    atr_len=24, sl_atr=6.0, tp_atr=4.0,
    month_entry_lock=0.01,
    taker=0.0004, maker=0.0001, slippage=0.0002, limit_penetration=0.0001,
)
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ----------------------------------------------------------------------------- data
def _get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "backtest"}), timeout=timeout) as r:
        return r.read()


def load(symbol, start, end, refresh=False):
    """1H candles incl. taker-buy volume for the months start..end (YYYY-MM), UTC, indexed by bar open."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s_1h_tbv_%s_%s.csv" % (symbol, start, end))
    if os.path.exists(path) and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    s = pd.Period(start, "M").to_timestamp().tz_localize("UTC")
    e = (pd.Period(end, "M") + 1).to_timestamp().tz_localize("UTC")
    rows = []
    try:                                                    # Binance spot REST
        cur = int(s.timestamp() * 1000)
        while cur < int(e.timestamp() * 1000):
            part = json.loads(_get("https://api.binance.com/api/v3/klines?symbol=%s&interval=1h&startTime=%d&limit=1000" % (symbol, cur)))
            if not part:
                break
            rows += part
            cur = part[-1][0] + 3600_000
            time.sleep(0.15)
    except Exception:                                       # fallback: GitHub mirror of the same klines
        rows = []
        for m in pd.period_range(start, end, freq="M"):
            try:
                rows += json.loads(_get("https://raw.githubusercontent.com/finom/static-klines/main/.klines-cache/%s/1h/%s-01.json" % (symbol, m.strftime("%Y-%m"))))
            except urllib.error.HTTPError:
                continue
    df = pd.DataFrame([r[:6] + [r[9]] for r in rows], columns=["t", "open", "high", "low", "close", "volume", "taker_buy"]).astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.drop_duplicates("t").set_index("t").sort_index()
    df = df[(df.index >= s) & (df.index < e)]
    df.to_csv(path)
    return df


# ----------------------------------------------------------------------------- signals
def signals(df, p):
    delta = 2 * df.taker_buy - df.volume                    # buy volume minus sell volume
    burst = delta.rolling(p["delta_bars"]).sum()
    z = (burst - burst.rolling(p["z_len"]).mean()) / burst.rolling(p["z_len"]).std()
    pc = df.close.shift(1)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    atr = tr.ewm(alpha=1.0 / p["atr_len"], adjust=False).mean()
    long = (z > p["z_k"]) & (z.shift(1) <= p["z_k"])
    short = (z < -p["z_k"]) & (z.shift(1) >= -p["z_k"])
    # shift by one bar: values at index i come from the bar that closed at i-1
    return (long.shift(1).fillna(False).to_numpy(bool), short.shift(1).fillna(False).to_numpy(bool),
            atr.shift(1).to_numpy())


# ----------------------------------------------------------------------------- engine
def backtest(df, p, anchor_day=1):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    long, short, atr = signals(df, p)
    taker, maker, slip, pen = p["taker"], p["maker"], p["slippage"], p["limit_penetration"]
    lock_at = p["month_entry_lock"] if p["month_entry_lock"] is not None else np.inf
    ts = df.index - pd.Timedelta(days=anchor_day - 1)
    month = (ts.year * 12 + ts.month).to_numpy()
    n = len(df)
    eq = np.zeros(n)
    trades = []
    pos, ep, sl, tp, eb = 0, 0.0, 0.0, 0.0, 0
    realized, month_start, locked, entered = 0.0, 0.0, False, False
    for i in range(1, n):
        if month[i] != month[i - 1]:
            month_start, locked, entered = eq[i - 1], False, False
        just_in = False
        if pos == 0 and not locked and np.isfinite(atr[i]):
            d = 1 if long[i] else (-1 if short[i] else 0)
            if d:
                pos, eb = d, i
                ep = o[i] * (1 + slip * d)
                sl = ep - d * p["sl_atr"] * atr[i]           # fixed at entry
                tp = ep + d * p["tp_atr"] * atr[i]           # fixed at entry
                realized -= taker
                just_in = entered = True
        if pos:
            px = fee = None
            if pos == 1:
                if not just_in and o[i] <= sl:
                    px, fee, why = o[i] * (1 - slip), taker, "SL"           # gap through the stop
                elif l[i] <= sl:
                    px, fee, why = sl * (1 - slip), taker, "SL"
                elif not just_in and h[i] >= tp * (1 + pen):
                    px, fee, why = max(tp, o[i]), maker, "TP"
            else:
                if not just_in and o[i] >= sl:
                    px, fee, why = o[i] * (1 + slip), taker, "SL"
                elif h[i] >= sl:
                    px, fee, why = sl * (1 + slip), taker, "SL"
                elif not just_in and l[i] <= tp * (1 - pen):
                    px, fee, why = min(tp, o[i]), maker, "TP"
            if px is not None:
                gross = pos * (px / ep - 1)
                realized += gross - fee
                trades.append((df.index[eb], df.index[i], pos, ep, sl, tp, px, why, gross - fee - taker))
                pos = 0
        unreal = pos * (c[i] * (1 - slip * pos) / ep - 1) - taker if pos else 0.0
        eq[i] = realized + unreal
        if not locked and entered and eq[i] - month_start >= lock_at:
            locked = True
    eq = pd.Series(eq, index=df.index)
    tr = pd.DataFrame(trades, columns=["entry_time", "exit_time", "side", "entry", "stop_loss", "take_profit", "exit", "exit_type", "net_ret"])
    return eq, tr


# ----------------------------------------------------------------------------- reporting
def monthly_table(eq, tr, start, end, anchor_day=1):
    shift = pd.Timedelta(days=anchor_day - 1)
    e = eq.copy()
    e.index = (e.index - shift).tz_localize(None)
    pnl = e.resample("ME").last().diff()
    pnl.index = pnl.index.to_period("M")
    pnl = pnl[start:end]
    g = tr.groupby((tr.entry_time - shift).dt.tz_localize(None).dt.to_period("M"))
    tab = pd.DataFrame({"net_pnl_%": (pnl * 100).round(2),
                        "trades": g.size().reindex(pnl.index).fillna(0).astype(int)})
    tab["result"] = np.where(tab["net_pnl_%"] > 0, "WIN", "LOSS")
    tab.index.name = "month"
    return tab


def summary(eq, tr, tab, start, end, p):
    lo = pd.Timestamp(start, tz="UTC")
    hi = (pd.Period(end, "M") + 1).to_timestamp().tz_localize("UTC")
    t = tr[(tr.entry_time >= lo) & (tr.entry_time < hi)]
    e = eq[(eq.index >= lo) & (eq.index < hi)]
    return {
        "months": len(tab),
        "profitable_months": int((tab["net_pnl_%"] > 0).sum()),
        "profitable_months_%": round(100 * (tab["net_pnl_%"] > 0).mean(), 1),
        "months_with_trades_%": round(100 * (tab["trades"] > 0).mean(), 1),
        "total_net_pnl_%": round(tab["net_pnl_%"].sum(), 1),
        "worst_month_%": tab["net_pnl_%"].min(),
        "max_drawdown_%": round(100 * (e - e.cummax()).min(), 1),
        "trades": len(t),
        "exits_TP / SL": "%d / %d" % ((t.exit_type == "TP").sum(), (t.exit_type == "SL").sum()),
        "trade_win_rate_%": round(100 * (t.net_ret > 0).mean(), 1),
        "avg_net_profit_per_trade_bps": round(1e4 * t.net_ret.mean(), 1),
        "avg_SL_distance_%": round(100 * ((t.entry - t.stop_loss).abs() / t.entry).mean(), 2),
        "avg_TP_distance_%": round(100 * ((t.take_profit - t.entry).abs() / t.entry).mean(), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-11")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--anchor-day", type=int, default=1, help="day of month on which monthly periods start")
    ap.add_argument("--no-lock", action="store_true", help="disable the monthly entry lock")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    p = dict(PARAMS)
    if a.no_lock:
        p["month_entry_lock"] = None
    warm = max(pd.Period(a.start, "M") - 2, pd.Period("2022-01", "M")).strftime("%Y-%m")
    data_end = a.end if a.anchor_day == 1 else (pd.Period(a.end, "M") + 1).strftime("%Y-%m")
    pd.set_option("display.width", 200)
    ok = True
    for sym in SYMBOLS:
        df = load(sym, warm, data_end, a.refresh)
        eq, tr = backtest(df, p, a.anchor_day)
        tab = monthly_table(eq, tr, a.start, a.end, a.anchor_day)
        s = summary(eq, tr, tab, a.start, a.end, p)
        print("\n" + "=" * 70 + "\n%s  1H  %s .. %s  (%d bars from %s)" % (sym, a.start, a.end, len(df), df.index[0].date()))
        print(tab.to_string())
        print()
        for k, v in s.items():
            print("  %-30s %s" % (k, v))
        ok &= s["profitable_months_%"] >= 80 and s["months_with_trades_%"] == 100
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            tab.to_csv(os.path.join(a.out, "%s_monthly.csv" % sym))
            tr.to_csv(os.path.join(a.out, "%s_trades.csv" % sym), index=False)
    print("\nACCEPTANCE (>=80%% profitable months and a trade in every month, both assets): %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
