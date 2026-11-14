#!/usr/bin/env python3
"""
Risk-sized test of two strategies on ten Binance USDT-M perpetuals, 1H candles, 2022-01 .. 2026-10.

Every trade is sized so that its stop-loss distance equals one risk unit (1R). With risk r per trade,
notional = r / (stop distance in %), so all PnL below is first computed in R and then converted:
PnL% = PnL_R x r  (r = 0.5% or 1%). Fees, slippage and funding scale with notional, so they scale too.

MOM  - momentum burst (two independent sleeves, each trade risks r)
       A: Bollinger z(20) crosses +/-2.5 -> follow, exit after 48 bars
       B: 1H return > 3 sigma(480) closing in the outer 40% of the bar -> follow,
          take-profit 2 x ATR(24) or exit after 48 bars
       protective stop 6 x ATR(24) on every trade (ADDED here: needed to define risk per trade)
       month lock: at month-to-date PnL >= +1R close everything, no new trades until next month
VOL  - volume-delta burst
       2-bar taker-buy minus taker-sell volume, z-scored over 336 bars, crosses +/-2.5 -> follow
       fixed stop 6 x ATR(24), fixed take-profit 4 x ATR(24), no other exit
       month lock: at month-to-date PnL >= +0.25R open no new trades until next month

Costs: taker 0.04% + 0.02% slippage per side (maker 0.01% on take-profit limits), real funding.
    python multi_coin_test.py --out results_multi_coin
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
FIRST, LAST = "2022-01", "2026-10"                 # reported calendar months
SPLIT = "2024-11"                                  # parameters were chosen on BTC/ETH from here on
BASE = "https://data.binance.vision/data/futures/um"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TAKER, MAKER, SLIP, PEN = 0.0004, 0.0001, 0.0002, 0.0001
STOP_ATR = 6.0
LOCK_R = {"MOM": 1.0, "VOL": 0.25}


# ----------------------------------------------------------------------------- data
def _zip_csv(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "backtest"}), timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    z = zipfile.ZipFile(io.BytesIO(raw))
    return z.read(z.namelist()[0]).decode()


def load(symbol):
    kp = os.path.join(CACHE, "%s_um_1h_2021.csv" % symbol)
    fp = os.path.join(CACHE, "%s_um_funding_2021.csv" % symbol)
    if os.path.exists(kp) and os.path.exists(fp):
        return pd.read_csv(kp, index_col=0, parse_dates=True), pd.read_csv(fp, index_col=0, parse_dates=True)["rate"]
    rows, frows = [], []
    for m in pd.period_range("2021-11", LAST, freq="M"):
        txt = _zip_csv("%s/monthly/klines/%s/1h/%s-1h-%s.zip" % (BASE, symbol, symbol, m))
        for ln in (txt or "").strip().splitlines():
            a = ln.split(",")
            if a[0].isdigit():
                rows.append([float(a[i]) for i in (0, 1, 2, 3, 4, 5, 9)])
        txt = _zip_csv("%s/monthly/fundingRate/%s/%s-fundingRate-%s.zip" % (BASE, symbol, symbol, m))
        for ln in (txt or "").strip().splitlines():
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
def _atr(df, n=24):
    pc = df.close.shift(1)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _sh(x):
    return x.shift(1).fillna(False).to_numpy(bool)


def sleeves(df, strat):
    """list of dict(long, short, tp_atr, hold); arrays are shifted so index i = signal from bar i-1."""
    c = df.close
    if strat == "MOM":
        z = (c - c.rolling(20).mean()) / c.rolling(20).std()
        lr = np.log(c).diff()
        r = lr / lr.rolling(480).std()
        loc = (c - df.low) / (df.high - df.low)
        return [dict(long=_sh((z > 2.5) & (z.shift(1) <= 2.5)), short=_sh((z < -2.5) & (z.shift(1) >= -2.5)), tp_atr=None, hold=48),
                dict(long=_sh((r > 3.0) & (loc > 0.6)), short=_sh((r < -3.0) & (loc < 0.4)), tp_atr=2.0, hold=48)]
    delta = 2 * df.taker_buy - df.volume
    b = delta.rolling(2).sum()
    z = (b - b.rolling(336).mean()) / b.rolling(336).std()
    return [dict(long=_sh((z > 2.5) & (z.shift(1) <= 2.5)), short=_sh((z < -2.5) & (z.shift(1) >= -2.5)), tp_atr=4.0, hold=None)]


# ----------------------------------------------------------------------------- engine (PnL in R)
def backtest(df, funding, strat, lock=True):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr = _atr(df).shift(1).to_numpy()
    sl_ = sleeves(df, strat)
    K, n = len(sl_), len(df)
    fbar = funding.groupby(funding.index.floor("1h")).sum().reindex(df.index).fillna(0.0).to_numpy()
    month = (df.index.year * 12 + df.index.month).to_numpy()
    lock_r = LOCK_R[strat] if lock else np.inf
    flatten_on_lock = strat == "MOM"
    pos = [0] * K; ep = [0.0] * K; sp = [0.0] * K; tp = [0.0] * K; eb = [0] * K; rr = [0.0] * K; acc = [0.0] * K
    eq = np.zeros(n); trades = []
    real = mstart = 0.0
    locked = entered = flat_next = False

    def close(j, i, px, fee, why):
        nonlocal real
        r = (pos[j] * (px / ep[j] - 1) - fee) / rr[j]
        real += r
        trades.append((df.index[eb[j]], df.index[i], j, pos[j], why, acc[j] + r))
        pos[j] = 0

    for i in range(1, n):
        if month[i] != month[i - 1]:
            mstart, locked, entered = eq[i - 1], False, False
        if fbar[i]:                                              # funding on positions carried into this bar
            for j in range(K):
                if pos[j]:
                    f = -pos[j] * fbar[i] / rr[j]
                    real += f; acc[j] += f
        if flat_next:
            for j in range(K):
                if pos[j]:
                    close(j, i, o[i] * (1 - SLIP * pos[j]), TAKER, "lock")
            flat_next, locked = False, True
        for j in range(K):
            s = sl_[j]; just = False
            if pos[j] == 0 and not locked and np.isfinite(atr[i]) and atr[i] > 0:
                d = 1 if s["long"][i] else (-1 if s["short"][i] else 0)
                if d:
                    pos[j], eb[j], just, entered = d, i, True, True
                    ep[j] = o[i] * (1 + SLIP * d)
                    sp[j] = ep[j] - d * STOP_ATR * atr[i]
                    tp[j] = ep[j] + d * s["tp_atr"] * atr[i] if s["tp_atr"] else np.inf * d
                    rr[j] = STOP_ATR * atr[i] / ep[j]             # 1R as a fraction of price
                    acc[j] = -TAKER / rr[j]
                    real += acc[j]
            if pos[j]:
                d = pos[j]
                if not just and s["hold"] and i - eb[j] >= s["hold"]:
                    close(j, i, o[i] * (1 - SLIP * d), TAKER, "time")
                elif not just and (o[i] - sp[j]) * d <= 0:
                    close(j, i, o[i] * (1 - SLIP * d), TAKER, "SL")
                elif (l[i] <= sp[j]) if d == 1 else (h[i] >= sp[j]):
                    close(j, i, sp[j] * (1 - SLIP * d), TAKER, "SL")
                elif not just and ((h[i] >= tp[j] * (1 + PEN)) if d == 1 else (l[i] <= tp[j] * (1 - PEN))):
                    close(j, i, max(tp[j], o[i]) if d == 1 else min(tp[j], o[i]), MAKER, "TP")
        eq[i] = real + sum((pos[j] * (c[i] * (1 - SLIP * pos[j]) / ep[j] - 1) - TAKER) / rr[j] for j in range(K) if pos[j])
        if not locked and entered and eq[i] - mstart >= lock_r:
            if flatten_on_lock:
                flat_next = True
            else:
                locked = True
    return pd.Series(eq, index=df.index), pd.DataFrame(trades, columns=["entry_time", "exit_time", "sleeve", "side", "exit_type", "pnl_R"])


# ----------------------------------------------------------------------------- reporting
def month_pnl(eq):
    e = eq.copy(); e.index = e.index.tz_localize(None)
    p = e.resample("ME").last().diff(); p.index = p.index.to_period("M")
    return p[FIRST:LAST]


def stats(p, eq=None, tr=None):
    out = {"months+": "%d/%d" % ((p > 0).sum(), len(p)), "months+_%": round(100 * (p > 0).mean()), "total_R": round(p.sum(), 1),
           "worst_month_R": round(p.min(), 1)}
    if eq is not None:
        e = eq[FIRST:]; out["maxDD_R"] = round(-(e - e.cummax()).min(), 1)
    if tr is not None:
        out["trades"] = len(tr); out["win_%"] = round(100 * (tr.pnl_R > 0).mean()); out["avg_R"] = round(tr.pnl_R.mean(), 3)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=None); a = ap.parse_args()
    pd.set_option("display.width", 250)
    data = {s: load(s) for s in SYMBOLS}
    for s, (df, _) in data.items():
        g = int((df.index.to_series().diff() != pd.Timedelta(hours=1)).sum() - 1)
        if g or df.index[0] > pd.Timestamp("2021-12-01", tz="UTC"):
            print("note: %s starts %s, %d gaps" % (s, df.index[0], g))
    for strat in ("MOM", "VOL"):
        for lock in (True, False):
            rows, mp = [], {}
            for s, (df, fr) in data.items():
                eq, tr = backtest(df, fr, strat, lock)
                p = month_pnl(eq); mp[s[:-4]] = p
                tr = tr[tr.entry_time >= pd.Timestamp(FIRST, tz="UTC")]
                em = tr.entry_time.dt.tz_localize(None).dt.to_period("M")
                r = {"coin": s[:-4]}; r.update(stats(p, eq, tr))
                r["min_trades/mo"] = int(tr.groupby(em).size().reindex(p.index).fillna(0).min())
                a_, b_ = p[:str(pd.Period(SPLIT) - 1)], p[SPLIT:]
                r["2022-01..2024-10"] = "%d/%d  %+.1fR" % ((a_ > 0).sum(), len(a_), a_.sum())
                r["2024-11..2026-10"] = "%d/%d  %+.1fR" % ((b_ > 0).sum(), len(b_), b_.sum())
                rows.append(r)
            tab = pd.DataFrame(rows).set_index("coin")
            M = pd.DataFrame(mp)
            port = M.sum(axis=1)
            print("\n" + "=" * 110 + "\n%s   month lock %s   (all figures in R; multiply by 0.5 or 1 for %% of equity)" % (strat, "ON" if lock else "OFF"))
            print(tab.to_string())
            cum = port.cumsum()
            print("ALL 10 COINS IN ONE ACCOUNT: months+ %d/%d (%.0f%%), total %+.1fR, worst month %.1fR, best %.1fR, max drawdown (month-end) %.1fR"
                  % ((port > 0).sum(), len(port), 100 * (port > 0).mean(), port.sum(), port.min(), port.max(), -(cum - np.maximum(cum.cummax(), 0)).min()))
            for yr, g in port.groupby(port.index.year):
                print("   %d: %+.1fR, %d/%d months +" % (yr, g.sum(), (g > 0).sum(), len(g)))
            if a.out:
                os.makedirs(a.out, exist_ok=True)
                nm = "%s_lock_%s" % (strat, "on" if lock else "off")
                tab.to_csv(os.path.join(a.out, nm + "_summary.csv")); M.round(3).to_csv(os.path.join(a.out, nm + "_monthly_R.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
