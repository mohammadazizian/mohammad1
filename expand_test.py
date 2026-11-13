"""Out-of-sample style test: version 1 stream W, rules unchanged, on coins it has never seen.

Run `python download_data.py` then `python expand_test.py`.
Writes results_expand/new_only (8 new coins, W only) and results_expand/combined
(the original 8 streams + 8 new W streams sharing one account).
"""
import contextlib
import io
import os

import numpy as np
import pandas as pd

import backtest as B
import download_data as D

NEW = ["BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "BCHUSDT"]
NEW_BASE_SL = 0.0100                                   # same base stop as the other alts (SOL, XRP)
ORIG_SL, ORIG_STREAMS = dict(B.BASE_SL), list(B.STREAMS)
ROOT = os.path.join(B.HERE, "results_expand")


def fetch_new():
    for s in NEW:
        if not os.path.exists(f"{B.DATA}/{s}_15m.pkl"):
            k, f = D.klines(s), D.funding(s)
            k.to_pickle(f"{B.DATA}/{s}_15m.pkl")
            f.to_pickle(f"{B.DATA}/{s}_funding.pkl")
            print(s, "klines", len(k), k.index[0], "->", k.index[-1], "| funding", len(f))


def run_cfg(name, base_sl, streams):
    B.BASE_SL, B.STREAMS, B.SYMBOLS = base_sl, streams, list(base_sl)
    B.OUT = os.path.join(ROOT, name)
    with contextlib.redirect_stdout(io.StringIO()):
        B.run()
    T = pd.read_csv(f"{B.OUT}/trades.csv", parse_dates=["entry_time", "exit_time"])
    E = pd.read_csv(f"{B.OUT}/equity_15m.csv", index_col=0, parse_dates=True)
    return T, E


def headline(T, E):
    m = E.mtm_equity
    years = (m.index[-1] - m.index[0] + pd.Timedelta(minutes=15)) / pd.Timedelta(days=365.25)
    final = E.realised_equity.iloc[-1]
    w, l = T[T.pnl > 0], T[T.pnl <= 0]
    ye = m.groupby(m.index.year).last()
    yr = (ye / ye.shift(1).fillna(B.EQUITY0) - 1) * 100
    d = dict(final_equity=final, cagr_pct=((final / B.EQUITY0) ** (1 / years) - 1) * 100,
             max_dd_pct=(m / np.maximum(m.cummax(), B.EQUITY0) - 1).min() * 100, trades=len(T),
             win_pct=len(w) / len(T) * 100, expectancy_R=T.R.mean(), profit_factor=w.pnl.sum() / -l.pnl.sum(),
             min_risk_pct=T.risk_pct_equity.min() * 100)
    d.update({f"ret_{y}_pct": v for y, v in yr.items()})
    return d


def by_coin(T):
    T = T.assign(year=T.entry_time.dt.year, coin=T.symbol.str.replace("USDT", ""))
    g = T.groupby("coin")
    tab = pd.DataFrame({"trades": g.size(), "win_%": g.pnl.apply(lambda x: (x > 0).mean() * 100),
                        "avg_R": g.R.mean(), "sum_R": g.R.sum()})
    yr = T.pivot_table(index="coin", columns="year", values="R", aggfunc="sum").add_prefix("sumR_")
    return tab.join(yr)


if __name__ == "__main__":
    fetch_new()
    new_sl = {s: NEW_BASE_SL for s in NEW}
    Tn, En = run_cfg("new_only", new_sl, [(s, "W") for s in NEW])
    # combined account: new alts slot in after SOL and XRP in the beta priority
    comb_streams = ORIG_STREAMS[:2] + [(s, "W") for s in NEW] + ORIG_STREAMS[2:]
    Tc, Ec = run_cfg("combined", {**ORIG_SL, **new_sl}, comb_streams)
    To, Eo = run_cfg("original", ORIG_SL, ORIG_STREAMS)

    H = pd.DataFrame({"original (8 streams)": headline(To, Eo), "new coins only (8 W streams)": headline(Tn, En),
                      "combined (16 streams)": headline(Tc, Ec)}).T
    allw = pd.concat([To[To.stream == "W"], Tn])
    tot = Tn.assign(year=Tn.entry_time.dt.year).groupby("year").R.agg(["size", "mean", "sum"])
    txt = "\n".join(["EXPANSION TEST - version 1 rules, stream W on unseen coins",
                     H.T.to_string(float_format=lambda x: f"{x:,.3f}"), "",
                     "Stream W by coin (R per trade is independent of account size); first 4 = original coins",
                     by_coin(allw).reindex([s.replace("USDT", "") for s in list(ORIG_SL) + NEW])
                     .to_string(float_format=lambda x: f"{x:+.3f}"), "",
                     "New coins pooled, by entry year (trades / avg R / sum R)",
                     tot.to_string(float_format=lambda x: f"{x:+.3f}")])
    print(txt)
    open(f"{ROOT}/report.txt", "w").write(txt + "\n")
    H.to_csv(f"{ROOT}/summary.csv")
