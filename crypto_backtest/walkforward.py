#!/usr/bin/env python3
"""
Walk-forward test of the momentum-burst strategy (1H, BTC + ETH).

Every `--step` months the parameters of each sleeve are re-selected using ONLY the previous
`--train` months (best t-statistic of net trade returns, BTC and ETH pooled), then traded for the
next `--step` months. The stitched result is therefore fully out-of-sample: no parameter was ever
chosen with knowledge of the months it was traded on.

Candidate grid (per sleeve)
    A: SMA length 16/20/24, z threshold 2.25/2.5/2.75, hold 24/48/72 bars
    B: impulse 2.5/3.0/3.5 sigma, take-profit 1.5/2/3 ATR or none, hold 24/48/72 bars
    regime filter for both: none | trend (longs above / shorts below SMA720) |
                            hours (entries 00:00-11:59 UTC only) | trend + hours

Pure Python: the first run simulates 504 variants and takes several minutes.

    python walkforward.py                    # 24-month training window, re-select every 6 months
    python walkforward.py --train 12 --step 3
"""
import argparse
import itertools

import numpy as np
import pandas as pd

import strategy as st

FILTERS = ["", "t", "h", "th"]
GRID_A = list(itertools.product([16, 20, 24], [2.25, 2.5, 2.75], [24, 48, 72], FILTERS))
GRID_B = list(itertools.product([2.5, 3.0, 3.5], [1.5, 2.0, 3.0, None], [24, 48, 72], FILTERS))


def _filter(df, long, short, f):
    c = df.close
    if "t" in f:
        up = c > c.rolling(720).mean()
        long, short = long & up, short & ~up
    if "h" in f:
        ok = pd.Series((df.index.hour + 1) % 24 < 12, index=df.index)   # next bar opens 00..11 UTC
        long, short = long & ok, short & ok
    return long, short


def _sh(x):
    return x.shift(1).fillna(False).to_numpy(dtype=bool)


def sleeve_a(df, n, k, hold, f):
    c = df.close
    z = (c - c.rolling(n).mean()) / c.rolling(n).std()
    long, short = _filter(df, (z > k) & (z.shift(1) <= k), (z < -k) & (z.shift(1) >= -k), f)
    return dict(long=_sh(long), short=_sh(short), tp=np.full(len(df), np.inf), hold=np.full(len(df), hold))


def sleeve_b(df, k, tp, hold, f):
    c = df.close
    lr = np.log(c).diff()
    r = lr / lr.rolling(480).std()
    loc = (c - df.low) / (df.high - df.low)
    long, short = _filter(df, (r > k) & (loc > 0.6), (r < -k) & (loc < 0.4), f)
    tpd = np.full(len(df), np.inf) if tp is None else (tp * st.atr(df, 24)).shift(1).fillna(np.inf).to_numpy()
    return dict(long=_sh(long), short=_sh(short), tp=tpd, hold=np.full(len(df), hold))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=24, help="training window in months")
    ap.add_argument("--step", type=int, default=6, help="re-selection interval in months")
    ap.add_argument("--first", default="2022-02", help="first month of data used for training")
    ap.add_argument("--end", default="2026-10")
    a = ap.parse_args()

    data = {s: st.load(s, "2022-01", a.end) for s in st.SYMBOLS}
    raw = dict(st.PARAMS, month_profit_lock=None)
    fams = {"A": (GRID_A, sleeve_a), "B": (GRID_B, sleeve_b)}

    print("simulating %d variants x %d assets ..." % (len(GRID_A) + len(GRID_B), len(data)))
    trades = {}
    for fam, (grid, fn) in fams.items():
        for g in grid:
            for s, df in data.items():
                trades[fam, g, s] = st.backtest(df, raw, sleeves=[fn(df, *g)])[1]

    def score(fam, g, lo, hi):
        r = np.concatenate([t.net_ret[(t.exit_time >= lo) & (t.exit_time < hi)].to_numpy()
                            for t in (trades[fam, g, s] for s in data)])
        return r.mean() / r.std() * np.sqrt(len(r)) if len(r) >= 30 and r.std() > 0 else -9.0

    t0 = pd.Timestamp(a.first, tz="UTC")
    last = (pd.Period(a.end, "M") + 1).to_timestamp().tz_localize("UTC")
    cuts = pd.date_range(t0 + pd.DateOffset(months=a.train), last - pd.Timedelta(days=1), freq="%dMS" % a.step)
    stitched = {s: {f: dict(long=np.zeros(len(df), bool), short=np.zeros(len(df), bool),
                            tp=np.full(len(df), np.inf), hold=np.full(len(df), 48)) for f in fams}
                for s, df in data.items()}
    print("\nparameters selected at each re-selection date (from the preceding %d months only):" % a.train)
    for c in cuts:
        lo, hi = c - pd.DateOffset(months=a.train), c + pd.DateOffset(months=a.step)
        for fam, (grid, fn) in fams.items():
            best = max(grid, key=lambda g: score(fam, g, lo, c))
            print("  %s  sleeve %s  %s" % (c.date(), fam, best))
            for s, df in data.items():
                v, m = fn(df, *best), (df.index >= c) & (df.index < hi)
                for k in ("long", "short", "tp", "hold"):
                    stitched[s][fam][k][m] = v[k][m]

    oos_start = cuts[0].strftime("%Y-%m")
    spans = [(oos_start, a.end)]
    if oos_start < "2024-11" <= a.end:
        spans += [(oos_start, "2024-10"), ("2024-11", a.end)]
    rows = []
    for lock in (None, st.PARAMS["month_profit_lock"]):
        p = dict(st.PARAMS, month_profit_lock=lock)
        for s, df in data.items():
            eq, tr = st.backtest(df, p, sleeves=[stitched[s]["A"], stitched[s]["B"]])
            for lo, hi in spans:
                tab = st.monthly_table(eq, tr, lo, hi)
                sm = st.summary(eq, tr, tab, lo, hi)
                rows.append(dict(symbol=s[:3], profit_lock="off" if lock is None else "%g%%" % (lock * 100),
                                 period="%s..%s" % (lo, hi),
                                 profitable_months="%d/%d" % (sm["profitable_months"], sm["months"]),
                                 total_pnl_pct=sm["total_net_pnl_%"], max_dd_pct=sm["max_drawdown_%"],
                                 worst_month_pct=sm["worst_month_%"], min_trades_month=sm["min_trades_in_a_month"],
                                 avg_trade_bps=sm["avg_net_profit_per_trade_bps"]))
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\nOUT-OF-SAMPLE walk-forward result (train %d m, step %d m):" % (a.train, a.step))
    print(out.to_string(index=False))
    return out


if __name__ == "__main__":
    main()
