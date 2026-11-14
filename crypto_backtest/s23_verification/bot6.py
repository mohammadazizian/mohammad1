"""
Six-coin bot: Strategy 2 (shock & flow momentum) and Strategy 3 (large-trade momentum), 15m bars,
EVERY trade protected by a stop loss, optional monthly loss lock.

Each coin is its own account (fixed capital, no compounding).  Per account and strategy:
  * stop loss  = stop_atr x ATR(96, Wilder) from entry, active from the entry bar (gap-aware, stop beats time exit)
  * profit lock: realised month PnL >= month_target  -> no new entries until next calendar month
  * loss lock  : realised month PnL <= -month_loss   -> no new entries until next calendar month (0 = off)
Costs: 0.04 % fee + 0.01 % slippage per side, plus funding.
"""
import sys
import numpy as np, pandas as pd

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
START = pd.Timestamp("2022-11-12", tz="UTC"); END = pd.Timestamp("2026-11-12", tz="UTC")
FEE = 0.0004; SLIP = 0.0001; VOL_WIN = 672; VOL_TARGET = 0.02; W_MAX = 1.0; ATR_N = 96

def load(sym, path="data"):
    d = pd.read_parquet(f"{path}/{sym}_5m.parquet")
    return d.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
                                    "quote_volume": "sum", "trades": "sum", "taker_buy_base": "sum", "funding": "sum"})

def common(d):
    c = d.close; lc = np.log(c); sg = lc.diff().rolling(VOL_WIN).std()
    tr = pd.concat([d.high - d.low, (d.high - c.shift()).abs(), (d.low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_N, adjust=False).mean().fillna(0).values
    w = (VOL_TARGET / (sg * np.sqrt(96))).clip(upper=W_MAX).fillna(0).values
    return lc, sg, atr, w

def signals_s2(d):
    """Shock (1h move > 4 sigma) and flow (4h net taker volume z > 3) momentum; level-triggered; hold 48 bars."""
    lc, sg, atr, w = common(d)
    z = (lc - lc.shift(4)) / (sg * 2.0)
    sS = (z > 4).astype(int) - (z < -4).astype(int)
    flow = (2 * d.taker_buy_base - d.volume).rolling(16).sum()
    fz = (flow - flow.rolling(VOL_WIN).mean()) / flow.rolling(VOL_WIN).std()
    sF = (fz > 3).astype(int) - (fz < -3).astype(int)
    return [sS.values, sF.values], [48, 48], w, atr

def signals_s3(d):
    """Average trade size over 1h, z > 2 vs 7 days -> follow the 1h price direction; edge-triggered; hold 96 bars."""
    lc, sg, atr, w = common(d)
    ats = d.quote_volume.rolling(4).sum() / d.trades.rolling(4).sum()
    az = (ats - ats.rolling(VOL_WIN).mean()) / ats.rolling(VOL_WIN).std()
    s = ((az > 2) * np.sign(d.close - d.close.shift(4))).fillna(0).astype(int)
    return [s.where(s != s.shift(1), 0).values], [96], w, atr

def backtest(d, sigfn, stop_atr=4.0, month_target=0.01, month_loss=0.0, start=START, end=END):
    sig, hold, w, atr = sigfn(d); K = len(sig)
    o = d.open.values; hi = d.high.values; lo = d.low.values; fund = d.funding.values; idx = d.index
    month = (idx.year * 12 + idx.month).values
    i0 = idx.searchsorted(start); i1 = idx.searchsorted(end); cost = 2 * (FEE + SLIP)
    pos = [0] * K; ep = [0.0] * K; sp = [0.0] * K; ei = [0] * K; wt = [0.0] * K; fd = [0.0] * K
    mpnl = 0.0; ment = 0; cur = -1; trades = []
    for i in range(i0, i1):
        if month[i] != cur: cur = month[i]; mpnl = 0.0; ment = 0
        for k in range(K):
            if pos[k] != 0:
                xp = 0.0; why = ""
                fd[k] += fund[i] * pos[k]
                if i - ei[k] >= hold[k] or i == i1 - 1: xp = o[i]; why = "time"
                if stop_atr > 0:
                    if pos[k] == 1 and o[i] <= sp[k]: xp = o[i]; why = "stop"
                    elif pos[k] == -1 and o[i] >= sp[k]: xp = o[i]; why = "stop"
                    elif xp == 0.0 and pos[k] == 1 and lo[i] <= sp[k]: xp = sp[k]; why = "stop"
                    elif xp == 0.0 and pos[k] == -1 and hi[i] >= sp[k]: xp = sp[k]; why = "stop"
                if xp != 0.0:
                    r = pos[k] * (xp / ep[k] - 1) - cost - fd[k]
                    trades.append((k, idx[ei[k]], idx[i], pos[k], wt[k], r, wt[k] * r, why))
                    mpnl += wt[k] * r; pos[k] = 0
        locked = (ment > 0 and mpnl >= month_target) or (month_loss > 0 and mpnl <= -month_loss)
        if not locked and i < i1 - 1:
            for k in range(K):
                s = sig[k][i - 1]
                if pos[k] == 0 and s != 0 and w[i - 1] > 0 and atr[i - 1] > 0:
                    pos[k] = int(s); ep[k] = o[i]; ei[k] = i; wt[k] = w[i - 1]; fd[k] = 0.0; ment += 1
                    if stop_atr > 0:
                        sp[k] = o[i] - pos[k] * stop_atr * atr[i - 1]
                        if (pos[k] == 1 and lo[i] <= sp[k]) or (pos[k] == -1 and hi[i] >= sp[k]):   # stopped on the entry bar
                            r = pos[k] * (sp[k] / ep[k] - 1) - cost
                            trades.append((k, idx[i], idx[i], pos[k], wt[k], r, wt[k] * r, "stop"))
                            mpnl += wt[k] * r; pos[k] = 0
    return pd.DataFrame(trades, columns=["sleeve", "entry", "exit", "dir", "weight", "ret", "pnl", "why"])

MONTHS = pd.period_range("2022-11", "2026-11", freq="M")
def monthly(tr):
    pe = tr.exit.dt.tz_localize(None).dt.to_period("M"); pn = tr.entry.dt.tz_localize(None).dt.to_period("M")
    return (tr.groupby(pe).pnl.sum().reindex(MONTHS).fillna(0) * 100), tr.groupby(pn).size().reindex(MONTHS).fillna(0).astype(int)

def stats(tr):
    m, c = monthly(tr); eq = tr.sort_values("exit").pnl.cumsum() * 100
    gp = tr.pnl[tr.pnl > 0].sum(); gl = -tr.pnl[tr.pnl < 0].sum()
    y = pd.Series(m.values, index=MONTHS)
    return dict(trades=len(tr), stopped=int((tr.why == "stop").sum()), months_pos=int((m > 0).sum()), months=len(m),
                months_no_trade=int((c == 0).sum()), net=round(m.sum(), 1),
                p1=round(y[:"2024-10"].sum() + 0, 1), p2=round(y["2024-11":].sum(), 1),
                worst=round(m.min(), 1), best=round(m.max(), 1), max_dd=round((eq.cummax() - eq).max(), 1),
                pf=round(gp / gl, 2) if gl > 0 else np.nan, win=round((tr.pnl > 0).mean() * 100, 1))

def run_all(sigfn, **kw):
    rows = {}; mm = {}
    for s in COINS:
        tr = backtest(load(s), sigfn, **kw); rows[s[:-4]] = stats(tr); mm[s[:-4]] = monthly(tr)[0]
    M = pd.DataFrame(mm); port = M.mean(axis=1); eq = port.cumsum()
    rows["PORTFOLIO(1/6 each)"] = dict(trades=sum(r["trades"] for r in rows.values()), stopped=sum(r["stopped"] for r in rows.values()),
        months_pos=int((port > 0).sum()), months=len(port), months_no_trade=0, net=round(port.sum(), 1),
        p1=round(port[:"2024-10"].sum(), 1), p2=round(port["2024-11":].sum(), 1), worst=round(port.min(), 1), best=round(port.max(), 1),
        max_dd=round((eq.cummax() - eq).max(), 1), pf=np.nan, win=np.nan)
    return pd.DataFrame(rows).T, M

if __name__ == "__main__":
    pd.set_option("display.width", 250)
    for name, fn in [("STRATEGY 2  shock & flow momentum", signals_s2), ("STRATEGY 3  large-trade momentum", signals_s3)]:
        for tag, kw in [("stop 4xATR, no loss lock", dict(month_loss=0.0)), ("stop 4xATR + monthly loss lock -5%", dict(month_loss=0.05))]:
            T, M = run_all(fn, **kw)
            print(f"\n=== {name} | {tag} ==="); print(T.to_string())
            M.round(2).to_csv(f"results/bot6_{name.split()[1]}_{'losslock' if kw['month_loss'] else 'base'}_monthly.csv")
