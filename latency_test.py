"""Latency test for version 1 (backtest.py): what happens if entries are late?

Signals, sizing, exits and costs are exactly those of backtest.py.  The only
change: instead of filling at the open of bar i, the order fills `delay` minutes
later at the open of that 1-minute candle.  Inside the entry bar the stop and
target only see the 1-minute highs/lows from the fill minute onward.

Run `python download_data.py`, `python download_1m.py`, then `python latency_test.py`.
"""
import os

import numpy as np
import pandas as pd

import backtest as B

DELAYS = [0, 1, 2, 3, 5, 10]                           # minutes after the bar open
OUT = os.path.join(B.HERE, "results_latency")


def prepare():
    last = min(pd.read_pickle(f"{B.DATA}/{s}_15m.pkl").index.max() for s in B.SYMBOLS)
    grid = pd.date_range(B.LOAD_START, min(B.BT_END, last), freq="15min")
    i0 = grid.get_loc(B.BT_START)
    M = {}
    for sym in B.SYMBOLS:
        k, _, _ = B.load(sym, grid)
        d = B.indicators(k)
        m1 = pd.read_pickle(f"{B.DATA}/{sym}_1m.pkl")
        g1 = pd.date_range(grid[i0], grid[-1] + pd.Timedelta(minutes=14), freq="1min")
        m1 = m1.reindex(g1)
        m1["close"] = m1.close.ffill()
        for c in ("open", "high", "low"):
            m1[c] = m1[c].fillna(m1.close)
        nb = len(grid) - i0
        o1, h1, l1 = (m1[c].values.reshape(nb, 15).copy() for c in ("open", "high", "low"))
        # the two Binance archives disagree on a handful of candles; count them, and keep delay 0
        # on the 15m candle so it reproduces backtest.py exactly
        nbad = int((~np.isclose(o1[:, 0], k.open.values[i0:], rtol=1e-9) | ~np.isclose(h1.max(1), k.high.values[i0:], rtol=1e-9)
                    | ~np.isclose(l1.min(1), k.low.values[i0:], rtol=1e-9)).sum())
        print(f"{sym}: {nbad} of {nb} bars differ between the 1m and 15m archives")
        o1[:, 0], h0, l0 = k.open.values[i0:], k.high.values[i0:], k.low.values[i0:]
        pad = lambda a: np.r_[np.full(i0, np.nan), a]
        M[sym] = dict(o=k.open.values, h=k.high.values, l=k.low.values, c=k.close.values,
                      cumf=k.cumf.values, dvol=d.d_vol.values, sig=B.signals(d),
                      px={dl: pad(o1[:, dl]) for dl in DELAYS},                 # fill price
                      hi={dl: pad(h1[:, dl:].max(1) if dl else h0) for dl in DELAYS},   # entry-bar high after the fill
                      lo={dl: pad(l1[:, dl:].min(1) if dl else l0) for dl in DELAYS})
    return grid, i0, M


def run(grid, i0, M, delay):
    n = len(grid)
    month = (grid.year * 12 + grid.month).values
    equity, open_notional, month_start, locked = B.EQUITY0, 0.0, B.EQUITY0, False
    pos, trades, mtm = {}, [], np.full(n, np.nan)
    last_exit = {s: -1 for s in B.STREAMS}

    def close(st, i, px, why):
        nonlocal equity, open_notional
        p = pos.pop(st)
        m = M[st[0]]
        fund = p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]])
        pnl = p["notional"] * (p["dir"] * (px / p["entry"] - 1) - B.COST - fund)
        equity += pnl
        open_notional -= p["notional"]
        last_exit[st] = i
        trades.append(dict(symbol=st[0], stream=st[1], dir=p["dir"], entry_time=grid[p["i"]], exit_time=grid[i],
                           entry=p["entry"], bar_open=m["o"][p["i"]], exit=px, reason=why, pnl=pnl,
                           R=pnl / (p["notional"] * p["sl"])))

    for i in range(i0, n):
        if month[i] != month[i - 1] and i > i0:
            month_start, locked = equity, False
        for st in list(pos):                           # A) exits at the open
            p, o = pos[st], M[st[0]]["o"][i]
            if i == p["i"] + B.HOLD[st[1]]:
                close(st, i, o, "time")
            elif (o <= p["stop"]) if p["dir"] > 0 else (o >= p["stop"]):
                close(st, i, o, "stop_gap")
        if equity <= month_start * (1 + B.MONTH_LOCK):
            locked = True
        for st in B.STREAMS:                           # B) entries, `delay` minutes after the open
            sym, typ = st
            m = M[sym]
            dr = int(m["sig"][typ][i - 1])
            if dr == 0 or st in pos or last_exit[st] >= i or locked:
                continue
            sl = B.BASE_SL[sym] + m["dvol"][i - 1]
            room = B.LEV_CAP * equity - open_notional
            if not np.isfinite(sl) or room <= 1e-12:
                continue
            notional = min(B.RISK * equity / sl, room)
            e = m["px"][delay][i]
            pos[st] = dict(i=i, dir=dr, entry=e, sl=sl, notional=notional,
                           stop=e * (1 - dr * sl), tp=e * (1 + dr * sl * B.TP_MULT[typ]))
            open_notional += notional
        for st in list(pos):                           # C) intrabar stop / target
            p, m = pos[st], M[st[0]]
            first = p["i"] == i                        # entry bar: only minutes after the fill count
            h = m["hi"][delay][i] if first else m["h"][i]
            l = m["lo"][delay][i] if first else m["l"][i]
            if p["dir"] > 0:
                if l <= p["stop"]:
                    close(st, i, p["stop"], "stop")
                elif h >= p["tp"]:
                    close(st, i, p["tp"], "target")
            else:
                if h >= p["stop"]:
                    close(st, i, p["stop"], "stop")
                elif l <= p["tp"]:
                    close(st, i, p["tp"], "target")
        u = 0.0
        for st, p in pos.items():
            m = M[st[0]]
            u += p["notional"] * (p["dir"] * (m["c"][i] / p["entry"] - 1) - B.COST
                                  - p["dir"] * (m["cumf"][i] - m["cumf"][p["i"]]))
        mtm[i] = equity + u
    for st in list(pos):
        close(st, n - 1, M[st[0]]["c"][n - 1], "end_of_data")
    return pd.DataFrame(trades), pd.Series(mtm[i0:], index=grid[i0:]), equity


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    grid, i0, M = prepare()
    years = (grid[-1] - grid[i0] + pd.Timedelta(minutes=15)) / pd.Timedelta(days=365.25)
    rows, streams, yearly = [], {}, {}
    for dl in DELAYS:
        T, mtm, final = run(grid, i0, M, dl)
        dd = (mtm / np.maximum(mtm.cummax(), B.EQUITY0) - 1).min()
        w, l = T[T.pnl > 0], T[T.pnl <= 0]
        adverse = (T.dir * (T.entry / T.bar_open - 1)).mean()      # how far price ran away before the fill
        rows.append(dict(delay_min=dl, final_equity=final, cagr_pct=((final / B.EQUITY0) ** (1 / years) - 1) * 100,
                         max_dd_pct=dd * 100, trades=len(T), win_pct=len(w) / len(T) * 100,
                         avg_win_R=w.R.mean(), avg_loss_R=l.R.mean(), expectancy_R=T.R.mean(),
                         profit_factor=w.pnl.sum() / -l.pnl.sum(), entry_drift_pct=adverse * 100))
        streams[dl] = T.groupby("stream").R.mean()
        ye = mtm.groupby(mtm.index.year).last()
        yearly[dl] = (ye / ye.shift(1).fillna(B.EQUITY0) - 1) * 100
        T.to_csv(f"{OUT}/trades_delay_{dl}m.csv", index=False)
    R = pd.DataFrame(rows).set_index("delay_min")
    S = pd.DataFrame(streams).T.rename_axis("delay_min")
    Y = pd.DataFrame(yearly).T.rename_axis("delay_min")
    txt = "\n".join(["LATENCY TEST - version 1 with entries filled N minutes after the bar open",
                     R.to_string(float_format=lambda x: f"{x:,.3f}"), "",
                     "Expectancy (R per trade) by stream type", S.to_string(float_format=lambda x: f"{x:+.4f}"), "",
                     "Return % by calendar year (MTM)", Y.to_string(float_format=lambda x: f"{x:+.2f}")])
    print(txt)
    open(f"{OUT}/report.txt", "w").write(txt + "\n")
    R.to_csv(f"{OUT}/summary.csv")
