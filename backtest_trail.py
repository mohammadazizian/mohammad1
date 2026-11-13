"""S / F / W streams with ATR trailing stop and dynamic slippage (Binance USDT-M, 15m).

Run `python download_data.py` first, then `python backtest_trail.py`.
Indicators, signals, ATR and funding (per-bar cumsum) are vectorised on a
pre-aligned 15m grid.  Only the portfolio pass is sequential, because
compounding equity, the shared notional cap, the monthly lock and the
path-dependent trailing stop cannot be expressed without state.

Timing (no look-ahead): signal on the close of bar i-1 -> fill at the open of
bar i.  The stop used during bar j is built only from bars up to j-1.
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, OUT = os.path.join(HERE, "data"), os.path.join(HERE, "results_trail")

LOAD_START = pd.Timestamp("2022-09-01", tz="UTC")
BT_START = pd.Timestamp("2022-11-13 00:00", tz="UTC")
BT_END = pd.Timestamp("2026-11-13 23:45", tz="UTC")

W_WEEK, W_TREND, W_RANK, ATR_N = 672, 2880, 17280, 14
BASE_SL = {"BTCUSDT": 0.0050, "ETHUSDT": 0.0075, "SOLUSDT": 0.0100, "XRPUSDT": 0.0100}
# beta priority by coin: SOL, XRP, ETH, BTC
STREAMS = [("SOLUSDT", "W"), ("XRPUSDT", "W"),
           ("ETHUSDT", "W"), ("ETHUSDT", "S"), ("ETHUSDT", "F"),
           ("BTCUSDT", "W"), ("BTCUSDT", "S"), ("BTCUSDT", "F")]
SYMBOLS = list(BASE_SL)
EQUITY0, RISK, LEV_CAP, MONTH_LOCK, VOL_CAP = 100.0, 0.005, 3.0, -0.15, 0.85
ACTIVATE_MULT, ATR_MULT = 1.5, 2.5
FEE_SIDE, SLIP_BASE, SLIP_Z, SLIP_FIXED = 0.0004, 0.0001, 0.0002, 0.00015


# ----------------------------------------------------------------------------- data
def load(sym, grid):
    k = pd.read_pickle(f"{DATA}/{sym}_15m.pkl").reindex(grid)
    n_missing = int(k.close.isna().sum())
    k["close"] = k.close.ffill()                       # missing candle -> flat bar at last close
    for c in ("open", "high", "low"):
        k[c] = k[c].fillna(k.close)
    vols = ["volume", "quote_volume", "count", "taker_buy_volume"]
    k[vols] = k[vols].fillna(0.0)
    f = pd.read_pickle(f"{DATA}/{sym}_funding.pkl")
    fbar = f.groupby(f.ts.dt.floor("15min")).rate.sum().reindex(grid).fillna(0.0)
    k["cumf"] = fbar.cumsum()                          # vectorised funding
    return k, n_missing, f.ts.max()


def indicators(k):
    c, v = k.close, k.volume
    r = np.log(c / c.shift(1))
    sigma = r.rolling(W_WEEK).std(ddof=1)
    d = pd.DataFrame(index=k.index)
    d["d_vol"] = sigma * np.sqrt(96)
    pc = c.shift(1)
    tr = np.maximum(k.high - k.low, np.maximum((k.high - pc).abs(), (k.low - pc).abs()))
    d["atr"] = tr.rolling(ATR_N).mean()                # ATR(14): mean true range over 14 bars
    d["z"] = np.log(c / c.shift(4)) / (sigma * 2)
    flow = (2 * k.taker_buy_volume - v).rolling(16).sum()
    d["fz"] = (flow - flow.rolling(W_WEEK).mean()) / flow.rolling(W_WEEK).std(ddof=1)
    ats = k.quote_volume.rolling(4).sum() / k["count"].rolling(4).sum()
    d["az"] = (ats - ats.rolling(W_WEEK).mean()) / ats.rolling(W_WEEK).std(ddof=1)
    d["vs"] = v.rolling(4).sum() / (4 * v.rolling(W_WEEK).mean())
    vw = lambda n: (v * c).rolling(n).sum() / v.rolling(n).sum()
    d["trend30"] = np.where(vw(W_WEEK) > vw(W_TREND), 1, -1)
    d["volrank"] = d.d_vol.rolling(W_RANK).rank(pct=True)
    d["up4"] = np.sign(c - c.shift(4))
    # per-side slippage implied by the bar's |z|: 0.01% + 0.02% * |z|/4 when |z| >= 4, else 0.015%
    az_ = d.z.abs().fillna(0.0)
    d["slip"] = np.where(az_ >= 4, SLIP_BASE + SLIP_Z * az_ / 4, SLIP_FIXED)
    return d


def signals(d):
    """Signal per bar close (+1 long / -1 short / 0) for each stream type."""
    z, fz, t = d.z, d.fz, d.trend30
    s = np.where((z > 4) & (fz > 1) & (t == 1), 1, np.where((z < -4) & (fz < -1) & (t == -1), -1, 0))
    f = np.where((fz > 3) & (z > 1) & (t == 1), 1, np.where((fz < -3) & (z < -1) & (t == -1), -1, 0))
    raw = np.where(d.az > 2, d.up4.fillna(0), 0)
    raw = np.where((z.abs() > 1) & (d.vs > 2.5), raw, 0).astype(int)
    prev = np.r_[0, raw[:-1]]
    w = np.where((raw != 0) & (raw != prev), raw, 0)
    ok = ~(d.volrank > VOL_CAP).values                 # volatility filter (NaN rank does not block)
    return {"S": s * ok, "F": f * ok, "W": w * ok}


# ----------------------------------------------------------------------------- portfolio pass
def run():
    os.makedirs(OUT, exist_ok=True)
    last = min(pd.read_pickle(f"{DATA}/{s}_15m.pkl").index.max() for s in SYMBOLS)
    grid = pd.date_range(LOAD_START, min(BT_END, last), freq="15min")
    M, info = {}, {}
    for sym in SYMBOLS:
        k, miss, flast = load(sym, grid)
        d = indicators(k)
        M[sym] = dict(o=k.open.values, h=k.high.values, l=k.low.values, c=k.close.values,
                      cumf=k.cumf.values, dvol=d.d_vol.values, atr=d.atr.values,
                      slip=d.slip.values, sig=signals(d), volrank=d.volrank.values)
        info[sym] = (miss, flast)
    n, i0 = len(grid), grid.get_loc(BT_START)
    month = (grid.year * 12 + grid.month).values

    equity, open_notional = EQUITY0, 0.0
    month_start, locked = EQUITY0, False
    pos, trades = {}, []
    last_exit = {s: -1 for s in STREAMS}
    mtm, realised, gross_lev = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    skipped = {"lock": 0, "cap_full": 0, "cap_reduced": 0, "busy": 0}

    def close(st, i, px, gap):
        nonlocal equity, open_notional
        p = pos.pop(st)
        m = M[st[0]]
        slip_out = m["slip"][i - 1] if not gap == "eod" else m["slip"][i]
        cost = 2 * FEE_SIDE + p["slip_in"] + slip_out
        fund = p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]])
        pnl = p["notional"] * (p["dir"] * (px / p["entry"] - 1) - cost - fund)
        equity += pnl
        open_notional -= p["notional"]
        last_exit[st] = i
        why = "end_of_data" if gap == "eod" else ("trailing_stop" if p["trailed"] else "initial_stop")
        trades.append(dict(symbol=st[0], stream=st[1], dir=p["dir"], entry_time=grid[p["i"]],
                           exit_time=grid[i], entry=p["entry"], exit=px, sl_pct=p["sl"],
                           notional=p["notional"], risk_usd=p["notional"] * p["sl"],
                           risk_pct_equity=p["notional"] * p["sl"] / p["eq"], reason=why,
                           gap_exit=gap is True, trail_activated=p["active"],
                           slip_in=p["slip_in"], slip_out=slip_out,
                           cost_usd=p["notional"] * cost, funding_usd=p["notional"] * fund,
                           pnl=pnl, R=pnl / (p["notional"] * p["sl"]), bars=i - p["i"]))

    for i in range(i0, n):
        if i > i0 and month[i] != month[i - 1]:        # new month: reset lock reference
            month_start, locked = equity, False
        # A) bar opens beyond the stop (initial or trailing) -> exit at the open
        for st in list(pos):
            p, o = pos[st], M[st[0]]["o"][i]
            if (o <= p["stop"]) if p["dir"] > 0 else (o >= p["stop"]):
                close(st, i, o, True)
        if equity <= month_start * (1 + MONTH_LOCK):
            locked = True
        # B) entries at the open from signals on the close of bar i-1, beta-priority order
        for st in STREAMS:
            sym, typ = st
            m = M[sym]
            dr = int(m["sig"][typ][i - 1])
            if dr == 0:
                continue
            if st in pos or last_exit[st] >= i:        # stream still held a position at the signal close
                skipped["busy"] += 1
                continue
            if locked:
                skipped["lock"] += 1
                continue
            sl = BASE_SL[sym] + m["dvol"][i - 1]       # d_vol at the signal-bar close
            if not np.isfinite(sl):
                continue
            want = RISK * equity / sl
            room = LEV_CAP * equity - open_notional
            if room <= 1e-12:
                skipped["cap_full"] += 1
                continue
            notional = min(want, room)
            skipped["cap_reduced"] += notional < want
            e = m["o"][i]
            pos[st] = dict(i=i, dir=dr, entry=e, sl=sl, notional=notional, eq=equity,
                           stop=e * (1 - dr * sl), act=e * (1 + dr * ACTIVATE_MULT * sl),
                           ext=e, active=False, trailed=False, slip_in=m["slip"][i - 1])
            open_notional += notional
        # C) intrabar stop check, then roll the trailing stop forward for the next bar
        for st in list(pos):
            p, m = pos[st], M[st[0]]
            h, l = m["h"][i], m["l"][i]
            if p["dir"] > 0:
                if l <= p["stop"]:
                    close(st, i, p["stop"], False)
                    continue
                p["ext"] = max(p["ext"], h)            # highest high since entry
                if not p["active"] and p["ext"] > p["act"]:
                    p["active"] = True
                if p["active"]:
                    new = p["ext"] - ATR_MULT * m["atr"][i]
                    if new > p["stop"]:
                        p["stop"], p["trailed"] = new, True
            else:
                if h >= p["stop"]:
                    close(st, i, p["stop"], False)
                    continue
                p["ext"] = min(p["ext"], l)            # lowest low since entry
                if not p["active"] and p["ext"] < p["act"]:
                    p["active"] = True
                if p["active"]:
                    new = p["ext"] + ATR_MULT * m["atr"][i]
                    if new < p["stop"]:
                        p["stop"], p["trailed"] = new, True
        # D) mark-to-market equity at the 15m close (entry-side costs + assumed exit costs booked)
        u = 0.0
        for st, p in pos.items():
            m = M[st[0]]
            u += p["notional"] * (p["dir"] * (m["c"][i] / p["entry"] - 1)
                                  - 2 * FEE_SIDE - p["slip_in"] - SLIP_FIXED
                                  - p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]]))
        mtm[i], realised[i] = equity + u, equity
        gross_lev[i] = open_notional / equity
    for st in list(pos):                               # still open when the data ends
        close(st, n - 1, M[st[0]]["c"][n - 1], "eod")
    realised[n - 1] = mtm[n - 1] = equity

    report(grid[i0:], mtm[i0:], realised[i0:], gross_lev[i0:], pd.DataFrame(trades), skipped, info, M, i0)


# ----------------------------------------------------------------------------- report
def report(idx, mtm, realised, lev, T, skipped, info, M, i0):
    T = T.sort_values(["entry_time", "exit_time"]).reset_index(drop=True)
    eq = pd.Series(realised, index=idx)
    per = idx.tz_localize(None).to_period("M")
    end_eq = eq.groupby(per).last()
    start_eq = end_eq.shift(1).fillna(EQUITY0)
    m = pd.Series(mtm, index=idx)
    end_mtm = m.groupby(per).last()
    monthly = pd.DataFrame({
        "trades_opened": T.groupby(T.entry_time.dt.tz_localize(None).dt.to_period("M")).size()
                          .reindex(end_eq.index).fillna(0).astype(int),
        "return_pct": (end_eq / start_eq - 1) * 100,
        "month_end_equity": end_eq,
        "mtm_return_pct": (end_mtm / end_mtm.shift(1).fillna(EQUITY0) - 1) * 100,
        "month_end_mtm_equity": end_mtm})
    monthly.index.name = "month"

    dd = m / np.maximum(m.cummax(), EQUITY0) - 1
    years = (idx[-1] - idx[0] + pd.Timedelta(minutes=15)) / pd.Timedelta(days=365.25)
    final = eq.iloc[-1]
    wins, losses = T[T.pnl > 0], T[T.pnl <= 0]
    C = T[T.reason != "end_of_data"]
    ini, trl = C[C.reason == "initial_stop"], C[C.reason == "trailing_stop"]
    desc = lambda g: (f"{len(g):5d} trades | win {100 * (g.pnl > 0).mean():6.2f} % | avg {g.R.mean():+.3f} R | "
                      f"sum {g.R.sum():+9.2f} R | pnl {g.pnl.sum():+9.2f} USD | gap-open exits {int(g.gap_exit.sum())} | "
                      f"avg hold {g.bars.mean() / 96:.2f} d")

    lines = ["=" * 100, f"Data used : {idx[0]}  ->  {idx[-1]}   ({years:.3f} years)"]
    for s, (miss, flast) in info.items():
        lines.append(f"  {s}: forward-filled candles={miss}, last funding print={flast:%Y-%m-%d %H:%M}, "
                     f"bars in window with NaN volrank={int(np.isnan(M[s]['volrank'][i0:]).sum())}")
    lines += ["", "1) MONTH-BY-MONTH (return_pct / month_end_equity = realised; mtm_* = mark-to-market)",
              monthly.to_string(float_format=lambda x: f"{x:,.2f}"), "",
              "2) HEADLINE",
              f"Final equity            : {final:,.2f} USD  (start {EQUITY0:.2f})",
              f"Total return            : {(final / EQUITY0 - 1) * 100:,.2f} %",
              f"CAGR                    : {((final / EQUITY0) ** (1 / years) - 1) * 100:,.2f} %",
              f"Max drawdown (MTM, 15m) : {dd.min() * 100:,.2f} %  (trough {dd.idxmin()})",
              f"Worst month (realised)  : {monthly.return_pct.idxmin()}  {monthly.return_pct.min():,.2f} %",
              f"Best month (realised)   : {monthly.return_pct.idxmax()}  {monthly.return_pct.max():,.2f} %",
              f"Worst month (MTM)       : {monthly.mtm_return_pct.idxmin()}  {monthly.mtm_return_pct.min():,.2f} %",
              f"Best month (MTM)        : {monthly.mtm_return_pct.idxmax()}  {monthly.mtm_return_pct.max():,.2f} %",
              f"Positive months         : {(monthly.return_pct > 0).sum()} / {len(monthly)} realised, "
              f"{(monthly.mtm_return_pct > 0).sum()} / {len(monthly)} MTM", "",
              "3) TRADES",
              f"Number of trades        : {len(T)}",
              f"Win rate                : {len(wins) / len(T) * 100:,.2f} %",
              f"Average win             : {wins.R.mean():+.3f} R   (median {wins.R.median():+.3f} R, max {wins.R.max():+.2f} R)",
              f"Average loss            : {losses.R.mean():+.3f} R   (median {losses.R.median():+.3f} R, min {losses.R.min():+.2f} R)",
              f"Expectancy              : {T.R.mean():+.4f} R per trade",
              f"Profit factor           : {wins.pnl.sum() / -losses.pnl.sum():.3f}",
              f"Avg risk per trade      : {T.risk_pct_equity.mean() * 100:.4f} % of equity "
              f"(min {T.risk_pct_equity.min() * 100:.4f} %, max {T.risk_pct_equity.max() * 100:.4f} %)",
              f"Avg initial SL distance : {T.sl_pct.mean() * 100:.3f} %",
              f"Avg holding time        : {T.bars.mean() / 96:.2f} days (median {T.bars.median() / 96:.2f}, max {T.bars.max() / 96:.1f})",
              f"Open notional / equity  : mean {lev.mean():.2f}x, max {lev.max():.2f}x",
              f"Signals not taken       : stream busy={skipped['busy']}, month-lock={skipped['lock']}, "
              f"cap full={skipped['cap_full']}; size reduced by cap={int(skipped['cap_reduced'])}", "",
              "4) EXIT ANALYTICS",
              f"Initial stop   : {desc(ini)}",
              f"Trailing stop  : {desc(trl)}",
              f"End of data    : {int((T.reason == 'end_of_data').sum())} trades closed at the last close "
              f"(pnl {T[T.reason == 'end_of_data'].pnl.sum():+.2f} USD)",
              f"Trail activated (reached +1.5 x SL) on {int(T.trail_activated.sum())} of {len(T)} trades", "",
              "COSTS",
              f"Fees + slippage           : {T.cost_usd.sum():,.2f} USD "
              f"(avg round trip {100 * (T.cost_usd.sum() / T.notional.sum()):.4f} % of notional)",
              f"Net funding paid          : {T.funding_usd.sum():,.2f} USD  (negative = received)",
              f"Gross PnL before costs    : {T.pnl.sum() + T.cost_usd.sum() + T.funding_usd.sum():,.2f} USD",
              f"Net PnL                   : {T.pnl.sum():,.2f} USD", "",
              "PER STREAM"]
    g = T.groupby(["symbol", "stream"])
    ps = pd.DataFrame({"trades": g.size(), "win_%": g.pnl.apply(lambda x: (x > 0).mean() * 100),
                       "avg_R": g.R.mean(), "sum_R": g.R.sum(), "pnl_usd": g.pnl.sum(),
                       "trail_exits": g.reason.apply(lambda x: (x == "trailing_stop").sum()),
                       "avg_days": g.bars.mean() / 96})
    lines.append(ps.to_string(float_format=lambda x: f"{x:,.3f}"))
    gd = T.groupby("dir")
    lines += ["", "BY DIRECTION", pd.DataFrame({"trades": gd.size(), "avg_R": gd.R.mean(),
                                                 "pnl_usd": gd.pnl.sum()}).to_string(float_format=lambda x: f"{x:,.3f}")]
    txt = "\n".join(lines)
    print(txt)
    open(f"{OUT}/report.txt", "w").write(txt + "\n")
    monthly.to_csv(f"{OUT}/monthly.csv")
    T.to_csv(f"{OUT}/trades.csv", index=False)
    pd.DataFrame({"mtm_equity": m, "realised_equity": eq}).to_csv(f"{OUT}/equity_15m.csv")


if __name__ == "__main__":
    run()
