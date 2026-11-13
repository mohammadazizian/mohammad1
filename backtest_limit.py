"""S / F / W streams with limit-pullback (maker) entries, 24h time exit and ATR trailing stop.

Binance USDT-M perpetuals, 15m bars.  Run `python download_data.py` first, then
`python backtest_limit.py`.

Indicators, signals, ATR and funding (per-bar cumsum) are vectorised on a
pre-aligned 15m grid.  The portfolio pass is a state machine over a list of
independent positions.

Timing (no look-ahead): signal on the close of bar i-1 -> limit order resting
during bar i at open_i * (1 -/+ 0.25 * d_vol[i-1]); filled at the limit price if
bar i trades through it, otherwise cancelled.  The stop used during bar j is
built only from bars up to j-1.
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, OUT = os.path.join(HERE, "data"), os.path.join(HERE, "results_limit")

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
EQUITY0, RISK, MONTH_LOCK, VOL_CAP = 100.0, 0.005, -0.15, 0.85
MAX_POS, COOLDOWN, HOLD, BUFFER = 5, 16, 96, 0.25   # positions, bars, bars, x d_vol
ACTIVATE_MULT, ATR_MULT = 1.5, 2.5
FEE_IN, FEE_OUT = 0.0002, 0.0004                   # maker entry, taker exit, zero slippage
COST = FEE_IN + FEE_OUT


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
                      sig=signals(d), volrank=d.volrank.values)
        info[sym] = (miss, flast)
    n, i0 = len(grid), grid.get_loc(BT_START)
    month = (grid.year * 12 + grid.month).values

    equity = EQUITY0
    month_start, locked = EQUITY0, False
    book, trades, orders = [], [], []                  # book = list of independent open positions
    last_open = {(st, d): -10**9 for st in STREAMS for d in (1, -1)}
    mtm, realised = np.full(n, np.nan), np.full(n, np.nan)
    n_open, gross_lev = np.zeros(n, dtype=int), np.zeros(n)
    funnel = {st: dict(signals=0, cooldown=0, lock=0, cap=0, placed=0, filled=0) for st in STREAMS}

    def close(p, i, px, why, gap=False):
        nonlocal equity
        m = M[p["sym"]]
        fund = p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]])
        pnl = p["notional"] * (p["dir"] * (px / p["entry"] - 1) - COST - fund)
        equity += pnl
        trades.append(dict(symbol=p["sym"], stream=p["typ"], dir=p["dir"], entry_time=grid[p["i"]],
                           exit_time=grid[i], bar_open=p["open"], entry=p["entry"], exit=px,
                           sl_pct=p["sl"], notional=p["notional"], risk_usd=p["notional"] * p["sl"],
                           risk_pct_equity=p["notional"] * p["sl"] / p["eq"], reason=why,
                           gap_exit=gap, trail_activated=p["active"],
                           cost_usd=p["notional"] * COST, funding_usd=p["notional"] * fund,
                           pnl=pnl, R=pnl / (p["notional"] * p["sl"]), bars=i - p["i"]))

    for i in range(i0, n):
        if i > i0 and month[i] != month[i - 1]:        # new month: reset lock reference
            month_start, locked = equity, False
        # A) exits at the open: stop gapped through (wins), else the 24h time exit
        alive = []
        for p in book:
            o = M[p["sym"]]["o"][i]
            if (o <= p["stop"]) if p["dir"] > 0 else (o >= p["stop"]):
                close(p, i, o, "trailing_stop" if p["trailed"] else "initial_stop", True)
            elif i == p["i"] + HOLD:
                close(p, i, o, "time")
            else:
                alive.append(p)
        book = alive
        if equity <= month_start * (1 + MONTH_LOCK):
            locked = True
        # B) limit pullback orders for signals on the close of bar i-1, beta-priority order
        for st in STREAMS:
            sym, typ = st
            m = M[sym]
            dr = int(m["sig"][typ][i - 1])
            dv = m["dvol"][i - 1]
            if dr == 0 or not np.isfinite(dv):
                continue
            fn = funnel[st]
            fn["signals"] += 1
            if i - last_open[(st, dr)] < COOLDOWN:     # same-direction fill less than 4h ago
                fn["cooldown"] += 1
                continue
            if locked:
                fn["lock"] += 1
                continue
            if len(book) >= MAX_POS:                   # no free slot -> no order
                fn["cap"] += 1
                continue
            fn["placed"] += 1
            o = m["o"][i]
            limit = o * (1 - dr * BUFFER * dv)
            filled = (m["l"][i] <= limit) if dr > 0 else (m["h"][i] >= limit)
            orders.append(dict(time=grid[i], symbol=sym, stream=typ, dir=dr, open=o, limit=limit, filled=filled))
            if not filled:                             # cancelled at the end of bar i
                continue
            fn["filled"] += 1
            sl = BASE_SL[sym] + dv
            book.append(dict(sym=sym, typ=typ, st=st, i=i, dir=dr, open=o, entry=limit, sl=sl,
                             notional=RISK * equity / sl, eq=equity, stop=limit * (1 - dr * sl),
                             act=limit * (1 + dr * ACTIVATE_MULT * sl), ext=limit,
                             active=False, trailed=False))
            last_open[(st, dr)] = i
        n_open[i] = len(book)
        gross_lev[i] = sum(p["notional"] for p in book) / equity
        # C) intrabar stop check, then roll each trailing stop forward for the next bar
        alive = []
        for p in book:
            m = M[p["sym"]]
            h, l = m["h"][i], m["l"][i]
            if p["dir"] > 0:
                if l <= p["stop"]:
                    close(p, i, p["stop"], "trailing_stop" if p["trailed"] else "initial_stop")
                    continue
                if i > p["i"]:                         # fill-bar extreme may predate the fill: not counted
                    p["ext"] = max(p["ext"], h)        # highest high since entry
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
                if i > p["i"]:
                    p["ext"] = min(p["ext"], l)        # lowest low since entry
                if not p["active"] and p["ext"] < p["act"]:
                    p["active"] = True
                if p["active"]:
                    new = p["ext"] + ATR_MULT * m["atr"][i]
                    if new < p["stop"]:
                        p["stop"], p["trailed"] = new, True
            alive.append(p)
        book = alive
        # D) mark-to-market equity at the 15m close (full round-trip cost booked)
        u = 0.0
        for p in book:
            m = M[p["sym"]]
            u += p["notional"] * (p["dir"] * (m["c"][i] / p["entry"] - 1) - COST
                                  - p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]]))
        mtm[i], realised[i] = equity + u, equity
    for p in book:                                     # still open when the data ends
        close(p, n - 1, M[p["sym"]]["c"][n - 1], "end_of_data")
    realised[n - 1] = mtm[n - 1] = equity

    conc = dict(n_open=pd.Series(n_open[i0:], index=grid[i0:]), lev=gross_lev[i0:])
    report(grid[i0:], mtm[i0:], realised[i0:], conc, pd.DataFrame(trades), pd.DataFrame(orders), funnel, info, M, i0)


# ----------------------------------------------------------------------------- report
def report(idx, mtm, realised, conc, T, O, funnel, info, M, i0):
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
    F = pd.DataFrame(funnel).T
    F.index = [f"{s[:3]}-{t}" for s, t in F.index]
    F.loc["TOTAL"] = F.sum()
    F["fill_%_of_orders"] = 100 * F.filled / F.placed
    F["fill_%_of_signals"] = 100 * F.filled / F.signals
    tot = F.loc["TOTAL"]
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
              f"Avg initial SL distance : {T.sl_pct.mean() * 100:.3f} %   | avg pullback buffer {100 * (T.entry / T.bar_open - 1).abs().mean():.3f} %",
              f"Avg holding time        : {T.bars.mean() / 4:.1f} h (median {T.bars.median() / 4:.1f} h)",
              "",
              "4) EXECUTION ANALYTICS (limit pullback orders)",
              f"Signals generated (after volatility filter) : {int(tot.signals)}",
              f"  blocked by 4h same-direction cooldown     : {int(tot.cooldown)}",
              f"  blocked by monthly loss lock              : {int(tot.lock)}",
              f"  blocked by 5-position cap (no free slot)  : {int(tot.cap)}",
              f"Limit orders placed                         : {int(tot.placed)}",
              f"  FILLED                                    : {int(tot.filled)}  = {tot['fill_%_of_orders']:.2f} % of orders placed, "
              f"{tot['fill_%_of_signals']:.2f} % of all signals",
              f"  cancelled (price never pulled back)       : {int(tot.placed - tot.filled)}",
              F.astype({c: int for c in ["signals", "cooldown", "lock", "cap", "placed", "filled"]})
               .to_string(float_format=lambda x: f"{x:,.2f}"),
              "",
              "EXIT ANALYTICS",
              f"Initial SL        : {desc(by('initial_stop'))}",
              f"ATR trailing stop : {desc(by('trailing_stop'))}",
              f"24h time exit     : {desc(by('time'))}",
              f"End of data       : {desc(by('end_of_data'))}",
              f"Trail activated (reached +1.5 x SL) on {int(T.trail_activated.sum())} of {len(T)} positions", "",
              "CONCURRENCY",
              f"Max concurrent positions : {int(no.max())}   | mean {no.mean():.2f} | bars at the 5-position cap: {100 * (no >= MAX_POS).mean():.2f} %",
              f"Open notional / equity   : mean {conc['lev'].mean():.2f}x, max {conc['lev'].max():.2f}x", "",
              "COSTS",
              f"Fees (0.02% maker in + 0.04% taker out) : {T.cost_usd.sum():,.2f} USD",
              f"Net funding paid                        : {T.funding_usd.sum():,.2f} USD  (negative = received)",
              f"Gross PnL before costs                  : {T.pnl.sum() + T.cost_usd.sum() + T.funding_usd.sum():,.2f} USD",
              f"Net PnL                                 : {T.pnl.sum():,.2f} USD", "",
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
    O.to_csv(f"{OUT}/orders.csv", index=False)
    F.to_csv(f"{OUT}/execution_funnel.csv")
    pd.DataFrame({"mtm_equity": m, "realised_equity": eq, "open_positions": no}).to_csv(f"{OUT}/equity_15m.csv")


if __name__ == "__main__":
    run()
