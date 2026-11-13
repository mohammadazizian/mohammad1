"""
Strategies 2 and 3 with FIXED stop-loss / take-profit (in % of entry price) and fixed-fractional money management.

One account trades several "streams" (strategy sleeve x coin).  For every trade:
  size   : notional = risk x equity / stop_pct   (a stopped trade loses `risk` of equity before costs),
           reduced if total open notional would exceed lev_cap x equity
  exits  : stop-loss (priority inside a bar, gap-aware), take-profit, or time exit after `hold` bars
  costs  : 0.04 % fee + 0.01 % slippage per side on notional, plus funding
Account rules: optional monthly loss lock (no new entries once month PnL <= -month_loss of month-start equity),
optional compounding (size from current realised equity).
"""
import numpy as np, pandas as pd
from numba import njit
import bot6 as B

START = B.START; END = B.END; MID = pd.Timestamp("2024-11-12", tz="UTC")
_cache = {}
def data(sym):
    if sym not in _cache:
        d = B.load(sym); s2, h2, _, _ = B.signals_s2(d); s3, h3, _, _ = B.signals_s3(d)
        _cache[sym] = dict(d=d, S=s2[0], F=s2[1], W=s3[0])
    return _cache[sym]
HOLD = {"S": 48, "F": 48, "W": 96}

@njit(cache=True)
def engine(o, h, l, fund, sig, hold, coin, slp, tpp, rm, month, i0, i1, risk, lev_cap, month_loss, compound, cost):
    S = sig.shape[1]; n = o.shape[0]
    pos = np.zeros(S, np.int64); ep = np.zeros(S); sp = np.zeros(S); tp = np.zeros(S); ei = np.zeros(S, np.int64)
    nt = np.zeros(S); fd = np.zeros(S)
    mx = (i1 - i0) * S // 2 + 10
    TE = np.empty(mx, np.int64); TX = np.empty(mx, np.int64); TS = np.empty(mx, np.int64); TD = np.empty(mx, np.int64)
    TP = np.empty(mx); TR = np.empty(mx); TK = np.empty(mx, np.int64); k = 0
    eq = 1.0; mstart = 1.0; cur = -1; eqc = np.ones(n)
    for i in range(i0, i1):
        if month[i] != cur: cur = month[i]; mstart = eq
        for s in range(S):
            if pos[s] != 0:
                c = coin[s]; xp = 0.0; kind = 0
                if i > ei[s]:
                    fd[s] += fund[i, c] * pos[s]
                    if i - ei[s] >= hold[s] or i == i1 - 1: xp = o[i, c]; kind = 3
                    if pos[s] == 1 and o[i, c] <= sp[s]: xp = o[i, c]; kind = 2
                    elif pos[s] == -1 and o[i, c] >= sp[s]: xp = o[i, c]; kind = 2
                if kind != 2:
                    if pos[s] == 1 and l[i, c] <= sp[s]: xp = sp[s]; kind = 2
                    elif pos[s] == -1 and h[i, c] >= sp[s]: xp = sp[s]; kind = 2
                    elif kind == 0 and tp[s] > 0:
                        if pos[s] == 1 and h[i, c] >= tp[s]: xp = tp[s]; kind = 1
                        elif pos[s] == -1 and l[i, c] <= tp[s]: xp = tp[s]; kind = 1
                if kind != 0:
                    r = pos[s] * (xp / ep[s] - 1.0) - cost - fd[s]
                    pnl = nt[s] * r; eq += pnl
                    TE[k] = ei[s]; TX[k] = i; TS[k] = s; TD[k] = pos[s]; TP[k] = pnl; TR[k] = r; TK[k] = kind; k += 1
                    pos[s] = 0; nt[s] = 0.0
        locked = month_loss > 0 and (eq / mstart - 1.0) <= -month_loss
        if not locked and i < i1 - 1 and i > 0:
            base = eq if compound else 1.0
            for s in range(S):
                sg = sig[i - 1, s]
                if pos[s] == 0 and sg != 0:
                    c = coin[s]; want = risk * rm[s] * base / slp[s]
                    room = lev_cap * base - nt.sum()
                    if want > room: want = room
                    if want <= 0: continue
                    pos[s] = sg; ep[s] = o[i, c]; ei[s] = i; nt[s] = want; fd[s] = 0.0
                    sp[s] = ep[s] * (1 - sg * slp[s]); tp[s] = ep[s] * (1 + sg * tpp[s]) if tpp[s] > 0 else 0.0
                    # same-bar exits handled on the next loop pass of this bar? no: check immediately (stop first)
                    xp = 0.0; kind = 0
                    if sg == 1 and l[i, c] <= sp[s]: xp = sp[s]; kind = 2
                    elif sg == -1 and h[i, c] >= sp[s]: xp = sp[s]; kind = 2
                    elif tp[s] > 0 and sg == 1 and h[i, c] >= tp[s]: xp = tp[s]; kind = 1
                    elif tp[s] > 0 and sg == -1 and l[i, c] <= tp[s]: xp = tp[s]; kind = 1
                    if kind != 0:
                        r = sg * (xp / ep[s] - 1.0) - cost
                        pnl = nt[s] * r; eq += pnl
                        TE[k] = i; TX[k] = i; TS[k] = s; TD[k] = sg; TP[k] = pnl; TR[k] = r; TK[k] = kind; k += 1
                        pos[s] = 0; nt[s] = 0.0
        eqc[i] = eq
    return TE[:k], TX[:k], TS[:k], TD[:k], TP[:k], TR[:k], TK[:k], eqc

def run(streams, sl, tp, hold=None, start=START, end=END, risk=0.01, lev_cap=1e9, month_loss=0.0, compound=False, rmult=None, cost=None):
    """streams: list of (coin, sleeve).  sl / tp: a number, {coin: v} or {(coin, sleeve): v}; tp 0 = none.  rmult: {sleeve: risk multiplier}."""
    coins = sorted({c for c, _ in streams}); ci = {c: j for j, c in enumerate(coins)}
    idx = data(coins[0])["d"].index
    o = np.column_stack([data(c)["d"].open.values for c in coins]); h = np.column_stack([data(c)["d"].high.values for c in coins])
    l = np.column_stack([data(c)["d"].low.values for c in coins]); f = np.column_stack([data(c)["d"].funding.values for c in coins])
    sig = np.column_stack([data(c)[s] for c, s in streams]).astype(np.int64)
    hd = np.array([(hold or HOLD)[s] if isinstance(hold or HOLD, dict) else hold for _, s in streams], np.int64)
    co = np.array([ci[c] for c, _ in streams], np.int64)
    def pick(x, c, sv):                                    # number, {coin: v} or {(coin, sleeve): v}
        if not isinstance(x, dict): return x
        return x[(c, sv)] if (c, sv) in x else x[c]
    slp = np.array([pick(sl, c, sv) for c, sv in streams], float); tpp = np.array([pick(tp, c, sv) for c, sv in streams], float)
    rm = np.array([(rmult or {}).get(sv, 1.0) for _, sv in streams], float)
    month = (idx.year * 12 + idx.month).values
    i0 = idx.searchsorted(start); i1 = idx.searchsorted(end)
    TE, TX, TS, TD, TP, TR, TK, eqc = engine(o, h, l, f, sig, hd, co, slp, tpp, rm, month, i0, i1, risk, lev_cap, month_loss, compound, 2 * (B.FEE + B.SLIP) if cost is None else cost)
    tr = pd.DataFrame({"entry": idx[TE], "exit": idx[TX], "stream": [f"{streams[s][0][:-4]}-{streams[s][1]}" for s in TS], "dir": TD,
                       "pnl": TP, "ret": TR, "kind": pd.Series(TK).map({1: "tp", 2: "sl", 3: "time"}).values})
    return tr, pd.Series(eqc[i0:i1], index=idx[i0:i1])

# ---- final configuration -------------------------------------------------------------------------------------------
S2_STREAMS = [("BTCUSDT", "S"), ("BTCUSDT", "F"), ("ETHUSDT", "S"), ("ETHUSDT", "F")]
S3_STREAMS = [("BTCUSDT", "W"), ("ETHUSDT", "W"), ("SOLUSDT", "W")]
SL = {("BTCUSDT", "S"): 0.010, ("BTCUSDT", "F"): 0.010, ("ETHUSDT", "S"): 0.015, ("ETHUSDT", "F"): 0.015,
      ("BTCUSDT", "W"): 0.0075, ("ETHUSDT", "W"): 0.010, ("SOLUSDT", "W"): 0.015}
TP = {("BTCUSDT", "S"): 0.040, ("BTCUSDT", "F"): 0.040, ("ETHUSDT", "S"): 0.060, ("ETHUSDT", "F"): 0.060,
      ("BTCUSDT", "W"): 0.045, ("ETHUSDT", "W"): 0.060, ("SOLUSDT", "W"): 0.090}
RMULT = {"S": 1.0, "F": 1.0, "W": 0.33}                      # Strategy 3 trades risk one third of a Strategy 2 trade

def account_stats(tr, eq, start=START, end=END):
    me = eq.resample("ME").last(); mr = me.pct_change(); mr.iloc[0] = me.iloc[0] / 1.0 - 1
    yrs = (end - start).days / 365.25; dd = (1 - eq / eq.cummax()).max()
    lev = None
    return dict(final=round(eq.iloc[-1], 2), cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), max_dd=round(dd * 100, 1),
                worst_month=round(mr.min() * 100, 1), best_month=round(mr.max() * 100, 1), months_pos=int((mr > 0).sum()), months=len(mr),
                trades=len(tr), by_year={int(y): round(v * 100, 1) for y, v in ((1 + mr).groupby(mr.index.year).prod() - 1).items()})

if __name__ == "__main__":
    pd.set_option("display.width", 250)
    for name, streams in [("Strategy 2 only (BTC, ETH)", S2_STREAMS), ("Strategy 2 + Strategy 3 (BTC, ETH, SOL)", S2_STREAMS + S3_STREAMS)]:
        for lock in [0.0, 0.05]:
            rows = []
            for r in [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03]:
                tr, eq = run(streams, SL, TP, risk=r, lev_cap=3.0, month_loss=lock, compound=True, rmult=RMULT)
                st = account_stats(tr, eq); rows.append(dict(risk_pct=r * 100, **st))
            print(f"\n=== {name} | compounding | leverage cap 3x | monthly loss lock {'-5%' if lock else 'off'} ===")
            print(pd.DataFrame(rows).to_string(index=False))
