#!/usr/bin/env python3
"""
Weekend-gap fade (sleeve A) + daily US-session fade (sleeve D) with a monthly governor.
Binance USDT-M perpetuals, 15m candles, funding included. Rules implemented exactly as specified;
nothing is optimised.

    python session_fade.py                 # downloads from data.binance.vision, prints all reports
    python session_fade.py --out results_session_fade
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

START = pd.Timestamp("2024-11-12 00:00", tz="UTC")
END = pd.Timestamp("2026-11-11 23:59", tz="UTC")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
BASE = "https://data.binance.vision/data/futures/um"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SIGMA_BARS = 672
HOLD_A, HOLD_D = 240, 96
MOVE_BARS, MOVE_K = 32, 0.5
TARGET_DAILY_VOL = 0.02
GOVERNOR = 0.025
FEE, SLIP = 0.0004, 0.0001          # per side


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


def _klines_frame(text):
    rows = [ln.split(",") for ln in text.strip().splitlines() if ln and ln[0].isdigit()]   # skip header if present
    df = pd.DataFrame([r[:6] for r in rows], columns=["t", "open", "high", "low", "close", "volume"]).astype(float)
    return df


def load_klines(symbol):
    path = os.path.join(CACHE, "%s_um_15m_%s.csv" % (symbol, START.strftime("%Y%m")))
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    parts, missing = [], []
    months = pd.period_range((START - pd.Timedelta(days=40)).strftime("%Y-%m"), END.strftime("%Y-%m"), freq="M")
    for m in months:
        txt = _zip_csv("%s/monthly/klines/%s/15m/%s-15m-%s.zip" % (BASE, symbol, symbol, m))
        if txt is None:                                   # month not published yet -> daily files
            for d in pd.date_range(m.to_timestamp(), min(END.tz_localize(None), m.to_timestamp("M")), freq="D"):
                t2 = _zip_csv("%s/daily/klines/%s/15m/%s-15m-%s.zip" % (BASE, symbol, symbol, d.strftime("%Y-%m-%d")))
                if t2 is None:
                    missing.append(d.strftime("%Y-%m-%d"))
                else:
                    parts.append(_klines_frame(t2))
        else:
            parts.append(_klines_frame(txt))
    df = pd.concat(parts)
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.drop_duplicates("t").set_index("t").sort_index()
    if missing:
        print("  %s: daily kline files not available for %s" % (symbol, missing))
    os.makedirs(CACHE, exist_ok=True)
    df.to_csv(path)
    return df


def load_funding(symbol):
    path = os.path.join(CACHE, "%s_um_funding_%s.csv" % (symbol, START.strftime("%Y%m")))
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)["rate"]
    rows, missing = [], []
    for m in pd.period_range((START - pd.Timedelta(days=40)).strftime("%Y-%m"), END.strftime("%Y-%m"), freq="M"):
        txt = _zip_csv("%s/monthly/fundingRate/%s/%s-fundingRate-%s.zip" % (BASE, symbol, symbol, m))
        if txt is None:
            missing.append(str(m))
            continue
        for ln in txt.strip().splitlines():
            a = ln.split(",")
            if a[0].isdigit():
                rows.append((int(a[0]), float(a[-1])))    # calc_time, funding_interval_hours, last_funding_rate
    s = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC").round("1min"): r for t, r in rows}).sort_index()
    s.name = "rate"
    if missing:
        print("  %s: funding files not available for %s (funding assumed 0 there)" % (symbol, missing))
    os.makedirs(CACHE, exist_ok=True)
    s.to_frame().to_csv(path)
    return s


# ----------------------------------------------------------------------------- backtest
def backtest(df, funding, costs=True, governor=True):
    idx = df.index
    o, c = df.open.to_numpy(), df.close.to_numpy()
    n = len(df)
    lr = np.log(df.close).diff()
    sigma = lr.rolling(SIGMA_BARS).std().to_numpy()
    end_t = idx + pd.Timedelta(minutes=15)                      # bar end time
    dow, hh, mm = end_t.dayofweek.to_numpy(), end_t.hour.to_numpy(), end_t.minute.to_numpy()
    month = (idx.year * 12 + idx.month).to_numpy()
    f_t = funding.index.to_numpy() if costs else np.array([], dtype="datetime64[ns]")
    f_r = funding.to_numpy() if costs else np.array([])
    idx_np = idx.to_numpy()
    cost = 2 * (FEE + SLIP) if costs else 0.0
    i0, i1 = idx.searchsorted(START), idx.searchsorted(END, side="right") - 1   # first / last bar in window

    pos = {"A": None, "D": None}        # (direction, entry_idx, weight, exit_idx)
    hold = {"A": HOLD_A, "D": HOLD_D}
    ref = np.nan
    trades = []
    m_real, m_opened, cur_month = 0.0, 0, month[i0]

    def close(sl, i, px):
        nonlocal m_real
        d, ei, w, _ = pos[sl]
        a, b = np.searchsorted(f_t, idx_np[ei], "left"), np.searchsorted(f_t, idx_np[i], "left")
        fund = d * f_r[a:b].sum() if costs else 0.0                 # funding stamps in [entry, exit)
        ret = d * (px / o[ei] - 1) - cost - fund
        trades.append((sl, idx[ei], idx[i] if px == o[i] else end_t[i], d, w, o[ei], px, fund, ret, w * ret))
        m_real += w * ret
        pos[sl] = None

    for i in range(1, i1 + 1):
        if dow[i - 1] == 4 and hh[i - 1] == 21 and mm[i - 1] == 0:   # bar that ended Friday 21:00
            ref = c[i - 1]
        if i < i0:
            continue
        if month[i] != cur_month:
            cur_month, m_real, m_opened = month[i], 0.0, 0
        for sl in ("A", "D"):                                        # time exits at this bar's open
            if pos[sl] is not None and pos[sl][3] == i:
                close(sl, i, o[i])
        blocked = governor and m_real >= GOVERNOR and m_opened > 0
        s = i - 1                                                    # signal bar (just closed)
        if not blocked and np.isfinite(sigma[s]) and sigma[s] > 0:
            w = min(1.0, TARGET_DAILY_VOL / (sigma[s] * np.sqrt(96)))
            if pos["A"] is None and dow[s] == 0 and hh[s] == 6 and mm[s] == 0 and np.isfinite(ref) and c[s] != ref:
                pos["A"] = (-1 if c[s] > ref else 1, i, w, i + HOLD_A)
                m_opened += 1
            if hh[s] == 19 and mm[s] == 0 and s - MOVE_BARS >= 0:
                move = np.log(c[s] / c[s - MOVE_BARS]) / (sigma[s] * np.sqrt(MOVE_BARS))
                if abs(move) > MOVE_K and pos["D"] is None:
                    pos["D"] = (-1 if move > 0 else 1, i, w, i + HOLD_D)
                    m_opened += 1
    for sl in ("A", "D"):                                            # force-close at the last bar of the window
        if pos[sl] is not None:
            close(sl, i1, c[i1])
    return pd.DataFrame(trades, columns=["sleeve", "entry_time", "exit_time", "direction", "weight", "entry", "exit",
                                         "funding", "trade_ret", "pnl"]).sort_values("exit_time").reset_index(drop=True)


# ----------------------------------------------------------------------------- reporting


def monthly(tr):
    em = tr.entry_time.dt.tz_localize(None).dt.to_period("M")
    xm = tr.exit_time.dt.tz_localize(None).dt.to_period("M")
    MONTHS = pd.period_range(START.strftime("%Y-%m"), END.strftime("%Y-%m"), freq="M")
    tab = pd.DataFrame({
        "trades_opened": tr.groupby(em).size().reindex(MONTHS).fillna(0).astype(int),
        "net_pnl_%": (tr.groupby(xm).pnl.sum() * 100).reindex(MONTHS).fillna(0).round(2),
        "win_rate_%": (tr.groupby(xm).pnl.apply(lambda x: (x > 0).mean()) * 100).reindex(MONTHS).round(0),
    })
    tab.index.name = "month"
    return tab


def summary(tr):
    tab = monthly(tr)
    p = tab["net_pnl_%"]
    eq = tr.pnl.cumsum() * 100
    dd = (eq - np.maximum(eq.cummax(), 0)).min()
    gains, losses = tr.pnl[tr.pnl > 0].sum(), -tr.pnl[tr.pnl < 0].sum()
    return {
        "trades": len(tr),
        "profitable_months": "%d of %d (%.0f%%)" % ((p > 0).sum(), len(p), 100 * (p > 0).mean()),
        "min_trades_in_a_month": int(tab.trades_opened.min()),
        "total_net_pnl_%": round(p.sum(), 1),
        "trade_win_rate_%": round(100 * (tr.pnl > 0).mean(), 1),
        "profit_factor": round(gains / losses, 2) if losses > 0 else float("inf"),
        "worst_month_%": p.min(),
        "best_month_%": p.max(),
        "max_drawdown_%": round(-dd, 1),
        "sleeve_A_pnl_% (n)": "%.1f (%d)" % (tr.pnl[tr.sleeve == "A"].sum() * 100, (tr.sleeve == "A").sum()),
        "sleeve_D_pnl_% (n)": "%.1f (%d)" % (tr.pnl[tr.sleeve == "D"].sum() * 100, (tr.sleeve == "D").sum()),
        "total_funding_paid_%": round((tr.weight * tr.funding).sum() * 100, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--start", default=None, help="other window start, e.g. 2022-11-12 (same rules)")
    ap.add_argument("--end", default=None, help="other window end, e.g. 2024-11-11")
    a = ap.parse_args()
    global START, END
    if a.start:
        START = pd.Timestamp(a.start + " 00:00", tz="UTC")
    if a.end:
        END = pd.Timestamp(a.end + " 23:59", tz="UTC")
    pd.set_option("display.width", 200)
    for sym in SYMBOLS:
        df, fr = load_klines(sym), load_funding(sym)
        gaps = int((df.index.to_series().diff() != pd.Timedelta(minutes=15)).sum() - 1)
        print("\n" + "=" * 78)
        print("%s  USDT-M perp 15m  bars %s -> %s  (%d bars, %d gaps, %d funding prints)"
              % (sym, df.index[0], df.index[-1], len(df), gaps, len(fr)))
        runs = {"WITH COSTS, GOVERNOR ON": backtest(df, fr, True, True),
                "ZERO COSTS, GOVERNOR ON": backtest(df, fr, False, True),
                "WITH COSTS, GOVERNOR OFF": backtest(df, fr, True, False)}
        print("\nMonth-by-month (with costs, governor on; PnL booked in the month the trade closes)")
        print(monthly(runs["WITH COSTS, GOVERNOR ON"]).to_string())
        for name, tr in runs.items():
            print("\n" + name)
            for k, v in summary(tr).items():
                print("  %-24s %s" % (k, v))
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            monthly(runs["WITH COSTS, GOVERNOR ON"]).to_csv(os.path.join(a.out, "%s_monthly.csv" % sym))
            runs["WITH COSTS, GOVERNOR ON"].to_csv(os.path.join(a.out, "%s_trades.csv" % sym), index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
