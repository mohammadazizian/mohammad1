#!/usr/bin/env python3
"""
Momentum-Burst + Monthly Profit-Lock  --  BTC / ETH, 1H candles
================================================================

Two independent momentum "sleeves" per asset (each gets 50% of the asset's notional):

  Sleeve A  (Bollinger breakout)
      z = (close - SMA20) / STD20            (20 x 1H bars)
      LONG  when z crosses above +2.5,  SHORT when z crosses below -2.5
      exit: time stop after 48 bars (48 h)

  Sleeve B  (impulse bar)
      r  = 1H log return / rolling 480-bar std of 1H log returns
      LONG  when r > +3.0 and the bar closes in the top 40% of its range
      SHORT when r < -3.0 and the bar closes in the bottom 40% of its range
      exit: resting take-profit limit at 2.0 x ATR(24)  or time stop after 48 bars

  Monthly governor (applies to the whole asset account)
      Mark-to-market month-to-date PnL is checked on every bar close.
      When it reaches +2.0% (of the asset's fixed notional) every open position is
      closed at the next bar's open and no new trade is opened until the next
      calendar month. The lock only arms after the month's first new entry, so every
      month contains at least one trade.

Execution model
      * signals are computed on a CLOSED bar, orders are filled at the NEXT bar's open
      * market fills: taker fee 0.04% + 0.02% slippage per side
      * take-profit limit fills: maker fee 0.01%, and price must trade THROUGH the
        limit by 1 bp to count as filled; never filled on the entry bar
      * fixed notional (no compounding, no leverage): PnL is in % of the asset notional
      * monthly PnL is mark-to-market (equity at month end minus equity at prior month end)

Usage
      python strategy.py                      # downloads data, runs the 24-month backtest
      python strategy.py --start 2022-02 --end 2024-10      # any other month range
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- parameters
PARAMS = dict(
    timeframe="1h",
    # sleeve A
    bb_len=20, bb_k=2.5, hold_a=48,
    # sleeve B
    vol_len=480, impulse_k=3.0, close_loc=0.6, atr_len=24, tp_atr=2.0, hold_b=48,
    # governor
    month_profit_lock=0.02,      # +2% month-to-date -> flatten and stand down
    month_loss_cap=None,         # optional symmetric rule, off by default
    # optional regime filter (off by default): only take longs above / shorts below the SMA of this length
    trend_filter=None,           # e.g. 720 (30 days of 1H bars)
    # costs
    taker=0.0004, maker=0.0001, slippage=0.0002, limit_penetration=0.0001,
)
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ----------------------------------------------------------------------------- data
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "backtest"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fetch_binance(symbol, start_ms, end_ms):
    """Binance spot REST klines (1h)."""
    rows, cur = [], start_ms
    while cur < end_ms:
        url = ("https://api.binance.com/api/v3/klines?symbol=%s&interval=1h&startTime=%d&limit=1000"
               % (symbol, cur))
        part = json.loads(_get(url))
        if not part:
            break
        rows += part
        cur = part[-1][0] + 3600_000
        time.sleep(0.15)
    return rows


def _fetch_mirror(symbol, start, end):
    """Fallback: github.com/finom/static-klines (daily refreshed mirror of Binance spot klines,
    one JSON file per calendar month for the 1h interval)."""
    rows = []
    for m in pd.period_range(start, end, freq="M"):
        url = ("https://raw.githubusercontent.com/finom/static-klines/main/.klines-cache/%s/1h/%s-01.json"
               % (symbol, m.strftime("%Y-%m")))
        try:
            rows += json.loads(_get(url))
        except urllib.error.HTTPError:                 # month not in the mirror (before 2022-01)
            continue
    return rows


def load(symbol, start, end, refresh=False):
    """1H OHLCV DataFrame indexed by bar OPEN time (UTC) for [start, end] (month strings)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s_1h_%s_%s.csv" % (symbol, start, end))
    if os.path.exists(path) and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    s = pd.Period(start, "M").to_timestamp().tz_localize("UTC")
    e = (pd.Period(end, "M") + 1).to_timestamp().tz_localize("UTC")
    try:
        rows = _fetch_binance(symbol, int(s.timestamp() * 1000), int(e.timestamp() * 1000))
        src = "binance"
    except Exception as ex:                                    # network restricted -> mirror
        print("  binance API unavailable (%s) -> using static-klines mirror" % type(ex).__name__)
        rows = _fetch_mirror(symbol, start, end)
        src = "mirror"
    df = pd.DataFrame([r[:6] for r in rows], columns=["t", "open", "high", "low", "close", "volume"]).astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.drop_duplicates("t").set_index("t").sort_index()
    df = df[(df.index >= s) & (df.index < e)]
    df.to_csv(path)
    print("  %s: %d bars %s -> %s (%s)" % (symbol, len(df), df.index[0], df.index[-1], src))
    return df


# ----------------------------------------------------------------------------- indicators
def atr(df, n):
    pc = df.close.shift(1)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()          # Wilder ATR


def signals(df, p):
    """Returns per-sleeve arrays already shifted by one bar: a signal at index i was
    computed from the bar that closed at i-1 and is executed at the open of bar i."""
    c = df.close
    # sleeve A: Bollinger z-score cross
    z = (c - c.rolling(p["bb_len"]).mean()) / c.rolling(p["bb_len"]).std()
    a_long = (z > p["bb_k"]) & (z.shift(1) <= p["bb_k"])
    a_short = (z < -p["bb_k"]) & (z.shift(1) >= -p["bb_k"])
    # sleeve B: volatility-normalised impulse bar closing near its extreme
    lr = np.log(c).diff()
    r = lr / lr.rolling(p["vol_len"]).std()
    loc = (c - df.low) / (df.high - df.low)
    b_long = (r > p["impulse_k"]) & (loc > p["close_loc"])
    b_short = (r < -p["impulse_k"]) & (loc < 1 - p["close_loc"])
    tp = p["tp_atr"] * atr(df, p["atr_len"])
    if p.get("trend_filter"):
        up = c > c.rolling(p["trend_filter"]).mean()
        a_long, b_long, a_short, b_short = a_long & up, b_long & up, a_short & ~up, b_short & ~up

    def sh(x):
        return x.shift(1).fillna(False).to_numpy(dtype=bool)

    big = np.full(len(df), np.inf)
    return [
        dict(long=sh(a_long), short=sh(a_short), tp=big, hold=p["hold_a"]),
        dict(long=sh(b_long), short=sh(b_short), tp=tp.shift(1).fillna(np.inf).to_numpy(), hold=p["hold_b"]),
    ]


# ----------------------------------------------------------------------------- engine
def backtest(df, p, anchor_day=1, sleeves=None):
    """Event-driven bar simulation. Returns (equity Series [fraction of notional, additive], trades DataFrame).
    anchor_day: day of month on which the governor's 'month' starts (1 = calendar months)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    sl = sleeves if sleeves is not None else signals(df, p)   # 'hold' may be an int or a per-bar array
    K = len(sl)
    w = 1.0 / K
    taker, maker, slip, pen = p["taker"], p["maker"], p["slippage"], p["limit_penetration"]
    X = p["month_profit_lock"] if p["month_profit_lock"] is not None else np.inf
    Y = p["month_loss_cap"] if p["month_loss_cap"] is not None else np.inf
    ts = df.index - pd.Timedelta(days=anchor_day - 1)
    mid = (ts.year * 12 + ts.month).to_numpy()

    pos = [0] * K
    ep = [0.0] * K
    tp = [0.0] * K
    eb = [0] * K
    hd = [0] * K
    eq = np.zeros(n)
    trades = []
    realized = 0.0
    month_start_eq = 0.0
    locked = False
    entered = False            # governor arms only after the month's first new entry
    flatten_next = False

    def close(j, i, px, fee, why):
        nonlocal realized
        gross = pos[j] * (px / ep[j] - 1)
        realized += w * (gross - fee)
        trades.append((df.index[eb[j]], df.index[i], "AB"[j], pos[j], ep[j], px, w * (gross - fee - taker), why))
        pos[j] = 0

    for i in range(1, n):
        if mid[i] != mid[i - 1]:                       # new month: reset governor
            month_start_eq = eq[i - 1]
            locked = False
            entered = False
        if flatten_next:                               # governor fired on previous close
            for j in range(K):
                if pos[j]:
                    close(j, i, o[i] * (1 - slip * pos[j]), taker, "month_lock")
            flatten_next = False
            locked = True
        for j in range(K):
            s = sl[j]
            just_in = False
            if pos[j] == 0 and not locked:
                d = 1 if s["long"][i] else (-1 if s["short"][i] else 0)
                if d:
                    pos[j] = d
                    ep[j] = o[i] * (1 + slip * d)      # market order at the open
                    tp[j] = ep[j] + d * s["tp"][i]
                    eb[j] = i
                    hd[j] = s["hold"] if np.isscalar(s["hold"]) else s["hold"][i]
                    realized -= w * taker
                    just_in = True
                    entered = True
            if pos[j] and not just_in:
                if i - eb[j] >= hd[j]:             # time stop at the open
                    close(j, i, o[i] * (1 - slip * pos[j]), taker, "time")
                elif pos[j] == 1 and h[i] >= tp[j] * (1 + pen):
                    close(j, i, max(tp[j], o[i]), maker, "tp")
                elif pos[j] == -1 and l[i] <= tp[j] * (1 - pen):
                    close(j, i, min(tp[j], o[i]), maker, "tp")
        # mark-to-market at liquidation value (pays slippage + taker to get out)
        unreal = sum(w * (pos[j] * (c[i] * (1 - slip * pos[j]) / ep[j] - 1) - taker) for j in range(K) if pos[j])
        eq[i] = realized + unreal
        if not locked and entered:
            mtd = eq[i] - month_start_eq
            if mtd >= X or mtd <= -Y:
                flatten_next = True

    eq = pd.Series(eq, index=df.index)
    tr = pd.DataFrame(trades, columns=["entry_time", "exit_time", "sleeve", "side", "entry", "exit", "net_ret", "reason"])
    return eq, tr


# ----------------------------------------------------------------------------- reporting
def monthly_table(eq, tr, start, end, anchor_day=1):
    shift = pd.Timedelta(days=anchor_day - 1)
    e = eq.copy()
    e.index = (e.index - shift).tz_localize(None)
    me = e.resample("ME").last()
    pnl = me.diff()
    pnl.index = pnl.index.to_period("M")
    pnl = pnl[start:end]
    et = (tr.entry_time - shift).dt.tz_localize(None).dt.to_period("M")
    g = tr.groupby(et)
    tab = pd.DataFrame({
        "net_pnl_%": (pnl * 100).round(2),
        "trades": g.size().reindex(pnl.index).fillna(0).astype(int),
        "win_rate_%": (g.net_ret.apply(lambda x: (x > 0).mean()) * 100).reindex(pnl.index).round(0),
    })
    tab["result"] = np.where(tab["net_pnl_%"] > 0, "WIN", "LOSS")
    tab.index.name = "month"
    return tab


def summary(eq, tr, tab, start, end):
    e = eq[start:end]
    t = tr[(tr.entry_time >= pd.Timestamp(start, tz="UTC")) & (tr.entry_time < (pd.Period(end, "M") + 1).to_timestamp().tz_localize("UTC"))]
    per_trade = t.net_ret * 2 * 1e4                    # bps on the sleeve's own notional
    return {
        "months": len(tab),
        "profitable_months": int((tab["net_pnl_%"] > 0).sum()),
        "profitable_months_%": round(100 * (tab["net_pnl_%"] > 0).mean(), 1),
        "months_with_trades_%": round(100 * (tab["trades"] > 0).mean(), 1),
        "min_trades_in_a_month": int(tab["trades"].min()),
        "total_net_pnl_%": round(tab["net_pnl_%"].sum(), 1),
        "best_month_%": tab["net_pnl_%"].max(),
        "worst_month_%": tab["net_pnl_%"].min(),
        "max_drawdown_%": round(100 * (e - e.cummax()).min(), 1),
        "trades": len(t),
        "trade_win_rate_%": round(100 * (t.net_ret > 0).mean(), 1),
        "avg_net_profit_per_trade_bps": round(per_trade.mean(), 1),
        "round_trip_cost_bps": round(1e4 * 2 * (PARAMS["taker"] + PARAMS["slippage"]), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-11", help="first month of the test (YYYY-MM)")
    ap.add_argument("--end", default="2026-10", help="last month of the test (YYYY-MM)")
    ap.add_argument("--anchor-day", type=int, default=1, help="day of month the monthly periods start on")
    ap.add_argument("--no-governor", action="store_true")
    ap.add_argument("--trend-filter", action="store_true", help="longs only above / shorts only below the 720-bar SMA")
    ap.add_argument("--refresh", action="store_true", help="re-download data")
    ap.add_argument("--out", default=None, help="directory for CSV output")
    a = ap.parse_args()

    p = dict(PARAMS)
    if a.no_governor:
        p["month_profit_lock"] = None
    if a.trend_filter:
        p["trend_filter"] = 720
    warm = max(pd.Period(a.start, "M") - 2, pd.Period("2022-01", "M")).strftime("%Y-%m")   # indicator warm-up
    data_end = a.end if a.anchor_day == 1 else (pd.Period(a.end, "M") + 1).strftime("%Y-%m")
    pd.set_option("display.width", 200)
    ok = True
    for sym in SYMBOLS:
        print("\n" + "=" * 78 + "\n%s  1H   %s .. %s%s" % (sym, a.start, a.end, "" if a.anchor_day == 1 else "  (months start on day %d)" % a.anchor_day))
        df = load(sym, warm, data_end, a.refresh)
        eq, tr = backtest(df, p, a.anchor_day)
        tab = monthly_table(eq, tr, a.start, a.end, a.anchor_day)
        s = summary(eq, tr, tab, a.start, a.end)
        print(tab.to_string())
        print()
        for k, v in s.items():
            print("  %-30s %s" % (k, v))
        ok &= s["profitable_months_%"] >= 70 and s["months_with_trades_%"] == 100 and s["avg_net_profit_per_trade_bps"] > 0
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            tab.to_csv(os.path.join(a.out, "%s_monthly.csv" % sym))
            tr.to_csv(os.path.join(a.out, "%s_trades.csv" % sym), index=False)
    print("\nACCEPTANCE (>=70%% profitable months, a trade in every month, on both assets): %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
