"""Multi-stream (S / F / W) intraday backtest on Binance USDT-M perpetuals, 15m bars.

Run `python download_data.py` first, then `python backtest.py`.
Indicators and signals are fully vectorised on a pre-aligned 15m grid; funding
is a per-bar cumsum.  Only the portfolio pass (compounding equity, shared
leverage cap, monthly lock) is sequential, because those couple all streams.
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, OUT = os.path.join(HERE, "data"), os.path.join(HERE, "results")

LOAD_START = pd.Timestamp("2022-09-01", tz="UTC")
BT_START = pd.Timestamp("2022-11-13 00:00", tz="UTC")
BT_END = pd.Timestamp("2026-11-13 23:45", tz="UTC")

W_WEEK, W_TREND, W_RANK = 672, 2880, 17280
BASE_SL = {"BTCUSDT": 0.0050, "ETHUSDT": 0.0075, "SOLUSDT": 0.0100, "XRPUSDT": 0.0100}
TP_MULT = {"S": 4.0, "F": 4.0, "W": 5.0}
HOLD = {"S": 48, "F": 48, "W": 96}
# beta priority: SOL-W, XRP-W, ETH-W, BTC-W, ETH-S/F, BTC-S/F
STREAMS = [("SOLUSDT", "W"), ("XRPUSDT", "W"), ("ETHUSDT", "W"), ("BTCUSDT", "W"),
           ("ETHUSDT", "S"), ("ETHUSDT", "F"), ("BTCUSDT", "S"), ("BTCUSDT", "F")]
SYMBOLS = list(BASE_SL)
EQUITY0, RISK, LEV_CAP, MONTH_LOCK, COST, VOL_CAP = 100.0, 0.005, 3.0, -0.15, 0.0010, 0.85


# ----------------------------------------------------------------------------- data
def load(sym, grid):
    k = pd.read_pickle(f"{DATA}/{sym}_15m.pkl").reindex(grid)
    n_missing = int(k.close.isna().sum())
    k["close"] = k.close.ffill()                       # missing candle -> flat bar at last close
    for c in ("open", "high", "low"):
        k[c] = k[c].fillna(k.close)
    k[["volume", "quote_volume", "count", "taker_buy_volume"]] = \
        k[["volume", "quote_volume", "count", "taker_buy_volume"]].fillna(0.0)
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
        sg = signals(d)
        M[sym] = dict(o=k.open.values, h=k.high.values, l=k.low.values, c=k.close.values,
                      cumf=k.cumf.values, dvol=d.d_vol.values, sig=sg, volrank=d.volrank.values)
        info[sym] = (miss, flast)
    n, i0 = len(grid), grid.get_loc(BT_START)
    month = (grid.year * 12 + grid.month).values

    equity, open_notional = EQUITY0, 0.0
    month_start, locked = EQUITY0, False
    pos = {}                                           # stream -> open position dict
    last_exit = {s: -1 for s in STREAMS}
    trades, mtm = [], np.full(n, np.nan)
    realised = np.full(n, np.nan)
    skipped = {"lock": 0, "cap_full": 0, "cap_reduced": 0}

    def close(st, i, px, why):
        nonlocal equity, open_notional
        p = pos.pop(st)
        m = M[st[0]]
        fund = p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]])
        gross = p["dir"] * (px / p["entry"] - 1)
        pnl = p["notional"] * (gross - COST - fund)
        equity += pnl
        open_notional -= p["notional"]
        last_exit[st] = i
        trades.append(dict(symbol=st[0], stream=st[1], dir=p["dir"], entry_time=grid[p["i"]],
                           exit_time=grid[i], entry=p["entry"], exit=px, sl_pct=p["sl"],
                           notional=p["notional"], risk_usd=p["notional"] * p["sl"],
                           risk_pct_equity=p["notional"] * p["sl"] / p["eq"], reason=why,
                           fee_usd=p["notional"] * COST, funding_usd=p["notional"] * fund, pnl=pnl,
                           R=pnl / (p["notional"] * p["sl"]), bars=i - p["i"]))

    for i in range(i0, n):
        if month[i] != month[i - 1] and i > i0:        # new month: reset lock reference
            month_start, locked = equity, False
        # A) exits at the open: time exit, or gap through the stop
        for st in list(pos):
            p, o = pos[st], M[st[0]]["o"][i]
            if i == p["i"] + HOLD[st[1]]:
                close(st, i, o, "time")
            elif (o <= p["stop"]) if p["dir"] > 0 else (o >= p["stop"]):
                close(st, i, o, "stop_gap")
        if equity <= month_start * (1 + MONTH_LOCK):
            locked = True
        # B) entries at the open from signals on bar i-1, in beta-priority order
        for st in STREAMS:
            sym, typ = st
            m = M[sym]
            dr = int(m["sig"][typ][i - 1])
            if dr == 0 or st in pos or last_exit[st] >= i:   # stream busy at the signal close
                continue
            if locked:
                skipped["lock"] += 1
                continue
            sl = BASE_SL[sym] + m["dvol"][i - 1]       # d_vol known at entry = signal-bar close
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
                           stop=e * (1 - dr * sl), tp=e * (1 + dr * sl * TP_MULT[typ]))
            open_notional += notional
        # C) intrabar stop / target (stop wins a tie); active from the entry bar
        for st in list(pos):
            p, m = pos[st], M[st[0]]
            if p["dir"] > 0:
                if m["l"][i] <= p["stop"]:
                    close(st, i, p["stop"], "stop")
                elif m["h"][i] >= p["tp"]:
                    close(st, i, p["tp"], "target")
            else:
                if m["h"][i] >= p["stop"]:
                    close(st, i, p["stop"], "stop")
                elif m["l"][i] <= p["tp"]:
                    close(st, i, p["tp"], "target")
        # D) mark-to-market equity at the 15m close
        u = 0.0
        for st, p in pos.items():
            m = M[st[0]]
            u += p["notional"] * (p["dir"] * (m["c"][i] / p["entry"] - 1) - COST
                                  - p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]]))
        mtm[i], realised[i] = equity + u, equity
    for st in list(pos):                               # still open when the data ends
        close(st, n - 1, M[st[0]]["c"][n - 1], "end_of_data")
    realised[n - 1] = equity

    report(grid[i0:], mtm[i0:], realised[i0:], pd.DataFrame(trades), skipped, info, M, i0)


# ----------------------------------------------------------------------------- report
def report(idx, mtm, realised, T, skipped, info, M, i0):
    T = T.sort_values(["entry_time", "exit_time"]).reset_index(drop=True)
    eq = pd.Series(realised, index=idx)
    per = idx.tz_localize(None).to_period("M")
    end_eq = eq.groupby(per).last()
    start_eq = end_eq.shift(1).fillna(EQUITY0)
    monthly = pd.DataFrame({
        "trades_opened": T.groupby(T.entry_time.dt.tz_localize(None).dt.to_period("M")).size()
                          .reindex(end_eq.index).fillna(0).astype(int),
        "return_pct": (end_eq / start_eq - 1) * 100,
        "month_end_equity": end_eq})
    monthly.index.name = "month"

    m = pd.Series(mtm, index=idx)
    dd = m / np.maximum(m.cummax(), EQUITY0) - 1
    years = (idx[-1] - idx[0] + pd.Timedelta(minutes=15)) / pd.Timedelta(days=365.25)
    final = eq.iloc[-1]
    wins, losses = T[T.pnl > 0], T[T.pnl <= 0]

    lines = ["=" * 78, f"Data used : {idx[0]}  ->  {idx[-1]}   ({years:.3f} years)"]
    for s, (miss, flast) in info.items():
        nanrank = int(np.isnan(M[s]["volrank"][i0:]).sum())
        lines.append(f"  {s}: forward-filled candles={miss}, last funding print={flast:%Y-%m-%d %H:%M}, "
                     f"bars in window with NaN volrank={nanrank}")
    lines += ["", "1) MONTH-BY-MONTH (realised equity)",
              monthly.to_string(float_format=lambda x: f"{x:,.2f}"), "",
              "2) HEADLINE",
              f"Final equity            : {final:,.2f} USD  (start {EQUITY0:.2f})",
              f"Total return            : {(final / EQUITY0 - 1) * 100:,.2f} %",
              f"CAGR                    : {((final / EQUITY0) ** (1 / years) - 1) * 100:,.2f} %",
              f"Max drawdown (MTM, 15m) : {dd.min() * 100:,.2f} %  (trough {dd.idxmin()})",
              f"Worst month             : {monthly.return_pct.idxmin()}  {monthly.return_pct.min():,.2f} %",
              f"Best month              : {monthly.return_pct.idxmax()}  {monthly.return_pct.max():,.2f} %",
              f"Positive months         : {(monthly.return_pct > 0).sum()} / {len(monthly)}", "",
              "3) TRADES",
              f"Number of trades        : {len(T)}",
              f"Win rate                : {len(wins) / len(T) * 100:,.2f} %",
              f"Average win             : {wins.R.mean():+.3f} R",
              f"Average loss            : {losses.R.mean():+.3f} R",
              f"Expectancy              : {T.R.mean():+.4f} R per trade",
              f"Profit factor           : {wins.pnl.sum() / -losses.pnl.sum():.3f}",
              f"Avg risk per trade      : {T.risk_pct_equity.mean() * 100:.4f} % of equity "
              f"(min {T.risk_pct_equity.min() * 100:.4f} %, max {T.risk_pct_equity.max() * 100:.4f} %)",
              f"Avg SL distance         : {T.sl_pct.mean() * 100:.3f} %",
              f"Exit reasons            : {T.reason.value_counts().to_dict()}",
              f"Signals skipped         : month-lock={skipped['lock']}, cap full={skipped['cap_full']}; "
              f"size reduced by cap={int(skipped['cap_reduced'])}", "",
              "4) COSTS",
              f"Fees + slippage (0.10% RT): {T.fee_usd.sum():,.2f} USD",
              f"Net funding paid          : {T.funding_usd.sum():,.2f} USD  (negative = received)",
              f"Total fees + funding      : {T.fee_usd.sum() + T.funding_usd.sum():,.2f} USD",
              f"Gross PnL before costs    : {T.pnl.sum() + T.fee_usd.sum() + T.funding_usd.sum():,.2f} USD",
              f"Net PnL                   : {T.pnl.sum():,.2f} USD", "",
              "PER STREAM"]
    g = T.groupby(["symbol", "stream"])
    ps = pd.DataFrame({"trades": g.size(), "win_%": g.pnl.apply(lambda x: (x > 0).mean() * 100),
                       "avg_R": g.R.mean(), "sum_R": g.R.sum(), "pnl_usd": g.pnl.sum(),
                       "fees_usd": g.fee_usd.sum()})
    lines.append(ps.to_string(float_format=lambda x: f"{x:,.3f}"))
    txt = "\n".join(lines)
    print(txt)
    open(f"{OUT}/report.txt", "w").write(txt + "\n")
    monthly.to_csv(f"{OUT}/monthly.csv")
    T.to_csv(f"{OUT}/trades.csv", index=False)
    pd.DataFrame({"mtm_equity": m, "realised_equity": eq}).to_csv(f"{OUT}/equity_15m.csv")


if __name__ == "__main__":
    run()
