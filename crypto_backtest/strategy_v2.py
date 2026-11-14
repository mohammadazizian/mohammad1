#!/usr/bin/env python3
"""
Momentum-Shock v2  --  Binance USDT-M perpetuals, 1H candles, fixed position size
==================================================================================

Idea: after an abnormal price shock, price tends to keep drifting the same way for a day or two
(under-reaction to new information). Two entry rules, each trading HALF of the fixed notional:

  A  breakout : z = (close - SMA20) / STD20 crosses above +2.5 -> LONG, below -2.5 -> SHORT
                stop 3 x ATR(24), take-profit 6 x ATR(24)   (risk : reward = 1 : 2)
  B  impulse  : 1H log-return > +3 sigma(480 bars) and close in the top 40% of the bar -> LONG
                (mirror for SHORT)
                stop 3 x ATR(24), take-profit 3 x ATR(24)   (risk : reward = 1 : 1)

  Both: stop and target are fixed at entry and never moved; a trade still open after 48 bars is
        closed at market. One position per rule; a rule ignores new signals while it is in a trade.

  Monthly profit lock: when month-to-date mark-to-market PnL reaches +2.0% of the notional (and at
        least one trade was opened this month) everything is closed at the next bar's open and no
        trade is opened until the next calendar month.

Execution model (what a bot can actually do)
  * signal on a CLOSED bar -> market order at the next bar's open
  * market / stop fills: taker 0.04% + 0.02% slippage; a stop gapped through is filled at the open
  * take-profit: resting limit, maker 0.01%, counted only if price trades 1 bp through it and never
    on the entry bar; if stop and target are inside the same bar the stop is assumed first
  * real funding payments on positions held through a funding timestamp
  * position size is the same fixed notional on every trade; no leverage, no compounding

    python strategy_v2.py --out results_v2            # BTC + ETH, 2022-01 .. 2026-10
    python strategy_v2.py --all-coins                 # ten large coins, summary only
"""
import argparse
import io
import os
import sys
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

P = dict(bb_len=20, bb_k=2.5, vol_len=480, imp_k=3.0, close_loc=0.6, atr_len=24,
         stop_atr=3.0, tp_atr_a=6.0, tp_atr_b=3.0, max_hold=48, month_lock=0.02, month_loss_cap=None,
         taker=0.0004, maker=0.0001, slippage=0.0002, limit_pen=0.0001)
FIRST, LAST = "2022-01", "2026-10"
TOP10 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
BASE = "https://data.binance.vision/data/futures/um"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ----------------------------------------------------------------------------- data
def _zip_csv(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "backtest"}), timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        raise
    z = zipfile.ZipFile(io.BytesIO(raw))
    return z.read(z.namelist()[0]).decode()


def load(symbol):
    """1H perpetual candles and funding rates from data.binance.vision (cached)."""
    kp = os.path.join(CACHE, "%s_um_1h_2021.csv" % symbol)
    fp = os.path.join(CACHE, "%s_um_funding_2021.csv" % symbol)
    if os.path.exists(kp) and os.path.exists(fp):
        return pd.read_csv(kp, index_col=0, parse_dates=True), pd.read_csv(fp, index_col=0, parse_dates=True)["rate"]
    rows, frows = [], []
    for m in pd.period_range("2021-11", LAST, freq="M"):
        for ln in _zip_csv("%s/monthly/klines/%s/1h/%s-1h-%s.zip" % (BASE, symbol, symbol, m)).strip().splitlines():
            a = ln.split(",")
            if a[0].isdigit():
                rows.append([float(a[i]) for i in (0, 1, 2, 3, 4, 5, 9)])
        for ln in _zip_csv("%s/monthly/fundingRate/%s/%s-fundingRate-%s.zip" % (BASE, symbol, symbol, m)).strip().splitlines():
            a = ln.split(",")
            if a[0].isdigit():
                frows.append((int(a[0]), float(a[-1])))
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "taker_buy"])
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.drop_duplicates("t").set_index("t").sort_index()
    fr = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC").round("1min"): r for t, r in frows}, name="rate").sort_index()
    os.makedirs(CACHE, exist_ok=True)
    df.to_csv(kp)
    fr.to_frame().to_csv(fp)
    return df, fr


# ----------------------------------------------------------------------------- signals
def signals(df, p):
    c = df.close
    z = (c - c.rolling(p["bb_len"]).mean()) / c.rolling(p["bb_len"]).std()
    lr = np.log(c).diff()
    r = lr / lr.rolling(p["vol_len"]).std()
    loc = (c - df.low) / (df.high - df.low)
    pc = c.shift(1)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    atr = tr.ewm(alpha=1.0 / p["atr_len"], adjust=False).mean()

    def sh(x):                                   # value at i = signal of the bar that closed at i-1
        return x.shift(1).fillna(False).to_numpy(bool)

    rules = [dict(name="A", long=sh((z > p["bb_k"]) & (z.shift(1) <= p["bb_k"])),
                  short=sh((z < -p["bb_k"]) & (z.shift(1) >= -p["bb_k"])), tp=p["tp_atr_a"]),
             dict(name="B", long=sh((r > p["imp_k"]) & (loc > p["close_loc"])),
                  short=sh((r < -p["imp_k"]) & (loc < 1 - p["close_loc"])), tp=p["tp_atr_b"])]
    return rules, atr.shift(1).to_numpy()


# ----------------------------------------------------------------------------- engine
def backtest(df, funding, p=P):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rules, atr = signals(df, p)
    K, n, w = len(rules), len(df), 1.0 / len(rules)
    taker, maker, slip, pen = p["taker"], p["maker"], p["slippage"], p["limit_pen"]
    lock = p["month_lock"] if p["month_lock"] is not None else np.inf
    cap = p["month_loss_cap"] if p["month_loss_cap"] is not None else np.inf
    fbar = funding.groupby(funding.index.floor("1h")).sum().reindex(df.index).fillna(0.0).to_numpy()
    month = (df.index.year * 12 + df.index.month).to_numpy()
    pos = [0] * K; ep = [0.0] * K; sl = [0.0] * K; tp = [0.0] * K; eb = [0] * K; acc = [0.0] * K
    eq = np.zeros(n); trades = []
    real = mstart = 0.0
    locked = entered = flat_next = False

    def close(j, i, px, fee, why):
        nonlocal real
        r = w * (pos[j] * (px / ep[j] - 1) - fee)
        real += r
        trades.append((df.index[eb[j]], df.index[i], rules[j]["name"], pos[j], ep[j], sl[j], tp[j], px, why, acc[j] + r))
        pos[j] = 0

    for i in range(1, n):
        if month[i] != month[i - 1]:
            mstart, locked, entered = eq[i - 1], False, False
        if fbar[i]:                                       # funding on positions carried into this bar
            for j in range(K):
                if pos[j]:
                    f = -pos[j] * fbar[i] * w
                    real += f; acc[j] += f
        if flat_next:                                     # monthly lock fired on the previous close
            for j in range(K):
                if pos[j]:
                    close(j, i, o[i] * (1 - slip * pos[j]), taker, "LOCK")
            flat_next, locked = False, True
        for j in range(K):
            just = False
            if pos[j] == 0 and not locked and np.isfinite(atr[i]) and atr[i] > 0:
                d = 1 if rules[j]["long"][i] else (-1 if rules[j]["short"][i] else 0)
                if d:
                    pos[j], eb[j], just, entered = d, i, True, True
                    ep[j] = o[i] * (1 + slip * d)
                    sl[j] = ep[j] - d * p["stop_atr"] * atr[i]
                    tp[j] = ep[j] + d * rules[j]["tp"] * atr[i]
                    acc[j] = -taker * w
                    real += acc[j]
            if pos[j]:
                d = pos[j]
                if not just and i - eb[j] >= p["max_hold"]:
                    close(j, i, o[i] * (1 - slip * d), taker, "TIME")
                elif not just and (o[i] - sl[j]) * d <= 0:
                    close(j, i, o[i] * (1 - slip * d), taker, "SL")
                elif (l[i] <= sl[j]) if d == 1 else (h[i] >= sl[j]):
                    close(j, i, sl[j] * (1 - slip * d), taker, "SL")
                elif not just and ((h[i] >= tp[j] * (1 + pen)) if d == 1 else (l[i] <= tp[j] * (1 - pen))):
                    close(j, i, max(tp[j], o[i]) if d == 1 else min(tp[j], o[i]), maker, "TP")
        eq[i] = real + sum(w * (pos[j] * (c[i] * (1 - slip * pos[j]) / ep[j] - 1) - taker) for j in range(K) if pos[j])
        if not locked and entered and (eq[i] - mstart >= lock or eq[i] - mstart <= -cap):
            flat_next = True
    cols = ["entry_time", "exit_time", "rule", "side", "entry", "stop_loss", "take_profit", "exit", "exit_type", "net_ret"]
    return pd.Series(eq, index=df.index), pd.DataFrame(trades, columns=cols)


# ----------------------------------------------------------------------------- reporting
def monthly(eq, tr):
    e = eq.copy(); e.index = e.index.tz_localize(None)
    pnl = e.resample("ME").last().diff(); pnl.index = pnl.index.to_period("M")
    pnl = pnl[FIRST:LAST] * 100
    cnt = tr.groupby(tr.entry_time.dt.tz_localize(None).dt.to_period("M")).size().reindex(pnl.index).fillna(0).astype(int)
    return pd.DataFrame({"net_pnl_%": pnl.round(2), "trades": cnt})


def summary(eq, tr, tab):
    t = tr[tr.entry_time >= pd.Timestamp(FIRST, tz="UTC")]
    p = tab["net_pnl_%"]
    e = eq[FIRST:] * 100
    wins, losses = t.net_ret[t.net_ret > 0], t.net_ret[t.net_ret <= 0]
    s = {"profitable_months": "%d / %d (%.0f%%)" % ((p > 0).sum(), len(p), 100 * (p > 0).mean()),
         "min_trades_in_a_month": int(tab.trades.min()),
         "total_net_pnl_%": round(p.sum(), 1),
         "worst_month_%": p.min(), "best_month_%": p.max(),
         "max_drawdown_%": round((e - e.cummax()).min(), 1),
         "trades": len(t), "trade_win_rate_%": round(100 * (t.net_ret > 0).mean(), 1),
         "avg_win / avg_loss": round(wins.mean() / -losses.mean(), 2),
         "exits TP/SL/TIME/LOCK": "/".join(str((t.exit_type == x).sum()) for x in ("TP", "SL", "TIME", "LOCK"))}
    for y, g in p.groupby(p.index.year):
        s["year_%d_%%" % y] = "%+.1f  (%d/%d months +)" % (g.sum(), (g > 0).sum(), len(g))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-coins", action="store_true")
    ap.add_argument("--no-lock", action="store_true")
    ap.add_argument("--loss-cap", type=float, default=None, help="optional: also stop for the month at this loss, e.g. 0.08")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    p = dict(P)
    if a.no_lock:
        p["month_lock"] = None
    p["month_loss_cap"] = a.loss_cap
    pd.set_option("display.width", 220)
    rows = []
    for sym in (TOP10 if a.all_coins else TOP10[:2]):
        df, fr = load(sym)
        eq, tr = backtest(df, fr, p)
        tab = monthly(eq, tr)
        s = summary(eq, tr, tab)
        rows.append(dict(coin=sym[:-4], **s))
        if not a.all_coins:
            print("\n" + "=" * 72 + "\n%s perpetual, 1H, %s .. %s" % (sym, FIRST, LAST))
            wide = pd.DataFrame({y: g["net_pnl_%"].to_numpy() if len(g) == 12 else np.r_[g["net_pnl_%"].to_numpy(), [np.nan] * (12 - len(g))]
                                 for y, g in tab.groupby(tab.index.year)}, index=range(1, 13))
            wide.index.name = "month"
            print("net PnL % per month (of the fixed notional)\n" + wide.to_string(na_rep=""))
            print()
            for k, v in s.items():
                print("  %-24s %s" % (k, v))
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            tab.to_csv(os.path.join(a.out, "%s_monthly.csv" % sym))
            tr.to_csv(os.path.join(a.out, "%s_trades.csv" % sym), index=False)
    if a.all_coins:
        print(pd.DataFrame(rows).set_index("coin").drop(columns=["best_month_%", "exits TP/SL/TIME/LOCK"]).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
