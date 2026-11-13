"""S / F / W streams with pyramiding, ATR trailing stop and momentum-reversal exits.

Binance USDT-M perpetuals, 15m bars.  Run `python download_data.py` first, then
`python backtest_pyramid.py`.

Indicators, signals, ATR, slippage and funding (per-bar cumsum) are vectorised on
a pre-aligned 15m grid.  The portfolio pass is a state machine over a list of
independent positions (own entry, stop, trailing state and size), because
compounding equity, the global notional cap, the monthly lock and the
path-dependent stops need state.

Timing (no look-ahead): signal on the close of bar i-1 -> fill at the open of
bar i.  The stop used during bar j is built only from bars up to j-1.  A flow
reversal seen on the close of bar j exits at the open of bar j+1.
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, OUT = os.path.join(HERE, "data"), os.path.join(HERE, "results_pyramid")

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
COOLDOWN, W_HOLD = 4, 96                          # bars
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
                      cumf=k.cumf.values, dvol=d.d_vol.values, atr=d.atr.values, fz=d.fz.values,
                      slip=d.slip.values, sig=signals(d), volrank=d.volrank.values)
        info[sym] = (miss, flast)
    n, i0 = len(grid), grid.get_loc(BT_START)
    month = (grid.year * 12 + grid.month).values

    equity, open_notional = EQUITY0, 0.0
    month_start, locked = EQUITY0, False
    book, trades = [], []                              # book = list of independent open positions
    last_open = {(st, d): -10**9 for st in STREAMS for d in (1, -1)}
    mtm, realised = np.full(n, np.nan), np.full(n, np.nan)
    n_open, gross_lev = np.zeros(n, dtype=int), np.zeros(n)
    max_stream = {st: 0 for st in STREAMS}
    skipped = {"cooldown": 0, "lock": 0, "cap_full": 0, "cap_reduced": 0}

    def close(p, i, px, why, gap=False):
        nonlocal equity, open_notional
        m = M[p["sym"]]
        slip_out = m["slip"][i] if why == "end_of_data" else m["slip"][i - 1]
        cost = 2 * FEE_SIDE + p["slip_in"] + slip_out
        fund = p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]])
        pnl = p["notional"] * (p["dir"] * (px / p["entry"] - 1) - cost - fund)
        equity += pnl
        open_notional -= p["notional"]
        trades.append(dict(symbol=p["sym"], stream=p["typ"], dir=p["dir"], entry_time=grid[p["i"]],
                           exit_time=grid[i], entry=p["entry"], exit=px, sl_pct=p["sl"],
                           notional=p["notional"], risk_usd=p["notional"] * p["sl"],
                           risk_pct_equity=p["notional"] * p["sl"] / p["eq"], reason=why,
                           gap_exit=gap, trail_activated=p["active"],
                           slip_in=p["slip_in"], slip_out=slip_out,
                           cost_usd=p["notional"] * cost, funding_usd=p["notional"] * fund,
                           pnl=pnl, R=pnl / (p["notional"] * p["sl"]), bars=i - p["i"]))

    for i in range(i0, n):
        if i > i0 and month[i] != month[i - 1]:        # new month: reset lock reference
            month_start, locked = equity, False
        # A) exits at the open: stop gapped through (wins), else flow reversal (S/F) or 24h time exit (W)
        alive = []
        for p in book:
            m = M[p["sym"]]
            o = m["o"][i]
            if (o <= p["stop"]) if p["dir"] > 0 else (o >= p["stop"]):
                close(p, i, o, "trailing_stop" if p["trailed"] else "initial_stop", True)
            elif p["typ"] != "W" and p["dir"] * m["fz"][i - 1] < 0:
                close(p, i, o, "reversal")
            elif p["typ"] == "W" and i == p["i"] + W_HOLD:
                close(p, i, o, "time")
            else:
                alive.append(p)
        book = alive
        if equity <= month_start * (1 + MONTH_LOCK):
            locked = True
        # B) entries at the open from signals on the close of bar i-1, beta-priority order
        for st in STREAMS:
            sym, typ = st
            m = M[sym]
            dr = int(m["sig"][typ][i - 1])
            if dr == 0:
                continue
            if i - last_open[(st, dr)] < COOLDOWN:     # same-direction entry less than 1h ago
                skipped["cooldown"] += 1
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
            book.append(dict(sym=sym, typ=typ, st=st, i=i, dir=dr, entry=e, sl=sl, notional=notional,
                             eq=equity, stop=e * (1 - dr * sl), act=e * (1 + dr * ACTIVATE_MULT * sl),
                             ext=e, active=False, trailed=False, slip_in=m["slip"][i - 1]))
            open_notional += notional
            last_open[(st, dr)] = i
        n_open[i], gross_lev[i] = len(book), open_notional / equity
        if book:
            cnt = {}
            for p in book:
                cnt[p["st"]] = cnt.get(p["st"], 0) + 1
            for st, v in cnt.items():
                if v > max_stream[st]:
                    max_stream[st] = v
        # C) intrabar stop check, then roll each trailing stop forward for the next bar
        alive = []
        for p in book:
            m = M[p["sym"]]
            h, l = m["h"][i], m["l"][i]
            if p["dir"] > 0:
                if l <= p["stop"]:
                    close(p, i, p["stop"], "trailing_stop" if p["trailed"] else "initial_stop")
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
                    close(p, i, p["stop"], "trailing_stop" if p["trailed"] else "initial_stop")
                    continue
                p["ext"] = min(p["ext"], l)            # lowest low since entry
                if not p["active"] and p["ext"] < p["act"]:
                    p["active"] = True
                if p["active"]:
                    new = p["ext"] + ATR_MULT * m["atr"][i]
                    if new < p["stop"]:
                        p["stop"], p["trailed"] = new, True
            alive.append(p)
        book = alive
        # D) mark-to-market equity at the 15m close (entry-side costs + assumed exit costs booked)
        u = 0.0
        for p in book:
            m = M[p["sym"]]
            u += p["notional"] * (p["dir"] * (m["c"][i] / p["entry"] - 1)
                                  - 2 * FEE_SIDE - p["slip_in"] - SLIP_FIXED
                                  - p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]]))
        mtm[i], realised[i] = equity + u, equity
    for p in book:                                     # still open when the data ends
        close(p, n - 1, M[p["sym"]]["c"][n - 1], "end_of_data")
    realised[n - 1] = mtm[n - 1] = equity

    conc = dict(n_open=pd.Series(n_open[i0:], index=grid[i0:]), lev=gross_lev[i0:], max_stream=max_stream)
    report(grid[i0:], mtm[i0:], realised[i0:], conc, pd.DataFrame(trades), skipped, info, M, i0)


# ----------------------------------------------------------------------------- report
def report(idx, mtm, realised, conc, T, skipped, info, M, i0):
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

    def desc(g):
        if not len(g):
            return "    0 positions"
        return (f"{len(g):5d} positions | win {100 * (g.pnl > 0).mean():6.2f} % | avg {g.R.mean():+.3f} R | "
                f"sum {g.R.sum():+9.2f} R | pnl {g.pnl.sum():+9.2f} USD | at-open (gap) {int(g.gap_exit.sum())} | "
                f"avg hold {g.bars.mean() / 4:.1f} h")

    by = lambda r: T[T.reason == r]
    no = conc["n_open"]
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
              f"Number of positions     : {len(T)}  ({(T.dir == 1).sum()} long, {(T.dir == -1).sum()} short)",
              f"Win rate                : {len(wins) / len(T) * 100:,.2f} %",
              f"Average win             : {wins.R.mean():+.3f} R   (median {wins.R.median():+.3f} R, max {wins.R.max():+.2f} R)",
              f"Average loss            : {losses.R.mean():+.3f} R   (median {losses.R.median():+.3f} R, min {losses.R.min():+.2f} R)",
              f"Expectancy              : {T.R.mean():+.4f} R per position",
              f"Profit factor           : {wins.pnl.sum() / -losses.pnl.sum():.3f}",
              f"Avg risk per position   : {T.risk_pct_equity.mean() * 100:.4f} % of equity "
              f"(min {T.risk_pct_equity.min() * 100:.4f} %, max {T.risk_pct_equity.max() * 100:.4f} %)",
              f"Avg initial SL distance : {T.sl_pct.mean() * 100:.3f} %",
              f"Avg holding time        : {T.bars.mean() / 4:.1f} h (median {T.bars.median() / 4:.1f} h, max {T.bars.max() / 96:.1f} d)",
              "",
              "4) EXIT ANALYTICS",
              f"(A) Initial SL        : {desc(by('initial_stop'))}",
              f"(B) ATR trailing stop : {desc(by('trailing_stop'))}",
              f"(C) Reversal / time   : {desc(T[T.reason.isin(['reversal', 'time'])])}",
              f"      flow reversal (S/F) : {desc(by('reversal'))}",
              f"      24h time exit (W)   : {desc(by('time'))}",
              f"    End of data       : {desc(by('end_of_data'))}",
              f"Trail activated (reached +1.5 x SL) on {int(T.trail_activated.sum())} of {len(T)} positions", "",
              "5) CONCURRENCY ANALYTICS",
              f"Max concurrent positions (portfolio) : {int(no.max())}  (first reached {no.idxmax()})",
              f"Mean concurrent positions            : {no.mean():.2f}   | share of bars with >=1 open: {100 * (no > 0).mean():.1f} %",
              "Max concurrent positions per stream  : "
              + ", ".join(f"{s[:3]}-{t}={v}" for (s, t), v in conc["max_stream"].items()),
              f"Open notional / equity               : mean {conc['lev'].mean():.2f}x, max {conc['lev'].max():.2f}x",
              f"Signals not taken                    : cooldown={skipped['cooldown']}, month-lock={skipped['lock']}, "
              f"cap full={skipped['cap_full']}; size reduced by cap={int(skipped['cap_reduced'])}", "",
              "COSTS",
              f"Fees + slippage           : {T.cost_usd.sum():,.2f} USD "
              f"(avg round trip {100 * (T.cost_usd.sum() / T.notional.sum()):.4f} % of notional)",
              f"Net funding paid          : {T.funding_usd.sum():,.2f} USD  (negative = received)",
              f"Gross PnL before costs    : {T.pnl.sum() + T.cost_usd.sum() + T.funding_usd.sum():,.2f} USD",
              f"Net PnL                   : {T.pnl.sum():,.2f} USD", "",
              "PER STREAM"]
    g = T.groupby(["symbol", "stream"])
    ps = pd.DataFrame({"positions": g.size(), "win_%": g.pnl.apply(lambda x: (x > 0).mean() * 100),
                       "avg_R": g.R.mean(), "sum_R": g.R.sum(), "pnl_usd": g.pnl.sum(),
                       "cost_usd": g.cost_usd.sum(), "avg_hours": g.bars.mean() / 4})
    lines.append(ps.to_string(float_format=lambda x: f"{x:,.3f}"))
    gd = T.groupby("dir")
    lines += ["", "BY DIRECTION", pd.DataFrame({"positions": gd.size(), "avg_R": gd.R.mean(),
                                                 "pnl_usd": gd.pnl.sum()}).to_string(float_format=lambda x: f"{x:,.3f}")]
    txt = "\n".join(lines)
    print(txt)
    open(f"{OUT}/report.txt", "w").write(txt + "\n")
    monthly.to_csv(f"{OUT}/monthly.csv")
    T.to_csv(f"{OUT}/trades.csv", index=False)
    pd.DataFrame({"mtm_equity": m, "realised_equity": eq, "open_positions": no}).to_csv(f"{OUT}/equity_15m.csv")


if __name__ == "__main__":
    run()
