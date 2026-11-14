"""
Large-Trade ("Whale") Momentum with Monthly Governor  --  BTCUSDT / ETHUSDT perpetuals, 15-minute bars.

Idea: when the average trade size (quote volume / number of trades) over a look-back window is unusually
large versus its own 7-day history, big participants are active.  Trade in the direction price moved over
that same window and hold for a fixed time, protected by an ATR stop.

Each (look, z, hold) triple is an independent sleeve holding at most one position.  A signal fires only on
the first bar the condition becomes true (or flips direction).
Orders are market orders at the open of the bar after the signal bar.  Sizing is volatility-targeted.
A monthly governor stops new entries for the rest of the calendar month once realised PnL >= month_target.
Costs: 0.04 % taker fee + 0.01 % slippage per side, plus actual funding.
"""
from dataclasses import dataclass, asdict
import numpy as np, pandas as pd

@dataclass
class Params:
    tf: str = "15min"
    sleeves: tuple = ((4, 2.0, 96),)                  # (look-back bars, z threshold, hold bars)
    stop_atr: float = 4.0                             # stop distance in ATR(96) multiples
    atr_n: int = 96
    vol_win: int = 96 * 7
    vol_target: float = 0.02; w_max: float = 1.0
    month_target: float = 0.01
    fee: float = 0.0004; slip: float = 0.0001

START = pd.Timestamp("2024-11-12", tz="UTC"); END = pd.Timestamp("2026-11-12", tz="UTC")
HOLD_START = pd.Timestamp("2022-11-12", tz="UTC")

def load(sym, tf="15min", path="data"):
    d = pd.read_parquet(f"{path}/{sym}_5m.parquet")
    return d.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
                               "quote_volume": "sum", "trades": "sum", "funding": "sum"})

def signals(d, p: Params):
    c = d.close; sg = np.log(c).diff().rolling(p.vol_win).std()
    tr = pd.concat([d.high - d.low, (d.high - c.shift()).abs(), (d.low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / p.atr_n, adjust=False).mean()
    sig = []
    for n, z, _ in p.sleeves:
        ats = d.quote_volume.rolling(n).sum() / d.trades.rolling(n).sum()          # average trade size
        az = (ats - ats.rolling(p.vol_win).mean()) / ats.rolling(p.vol_win).std()
        s = ((az > z) * np.sign(c - c.shift(n))).fillna(0).astype(int)
        sig.append(s.where(s != s.shift(1), 0).values)                             # first bar only
    w = (p.vol_target / (sg * np.sqrt(96))).clip(upper=p.w_max).fillna(0)
    return sig, [h for _, _, h in p.sleeves], w.values, atr.fillna(0).values

def backtest(d, p: Params = Params(), start=START, end=END):
    sig, hold, w, atr = signals(d, p); K = len(sig)
    o = d.open.values; hi = d.high.values; lo = d.low.values; fund = d.funding.values; idx = d.index
    month = (idx.year * 12 + idx.month).values
    i0 = idx.searchsorted(start); i1 = idx.searchsorted(end); cost = 2 * (p.fee + p.slip)
    pos = [0] * K; ep = [0.0] * K; sp = [0.0] * K; ei = [0] * K; wt = [0.0] * K; fd = [0.0] * K
    mpnl = 0.0; ment = 0; cur = -1; trades = []
    for i in range(i0, i1):
        if month[i] != cur: cur = month[i]; mpnl = 0.0; ment = 0
        for k in range(K):
            if pos[k] != 0:
                xp = 0.0
                if i > ei[k]:
                    fd[k] += fund[i] * pos[k]
                    if i - ei[k] >= hold[k] or i == i1 - 1: xp = o[i]              # time exit at bar open
                # protective stop, checked from the entry bar on (gap-aware, stop has priority intrabar)
                if pos[k] == 1 and o[i] <= sp[k]: xp = o[i]
                elif pos[k] == -1 and o[i] >= sp[k]: xp = o[i]
                elif xp == 0.0 and pos[k] == 1 and lo[i] <= sp[k]: xp = sp[k]
                elif xp == 0.0 and pos[k] == -1 and hi[i] >= sp[k]: xp = sp[k]
                if xp != 0.0:
                    r = pos[k] * (xp / ep[k] - 1) - cost - fd[k]
                    trades.append((k, idx[ei[k]], idx[i], pos[k], ep[k], xp, wt[k], r, wt[k] * r))
                    mpnl += wt[k] * r; pos[k] = 0
        if not (ment > 0 and mpnl >= p.month_target) and i < i1 - 1:
            for k in range(K):
                s = sig[k][i - 1]
                if pos[k] == 0 and s != 0 and w[i - 1] > 0 and atr[i - 1] > 0:
                    pos[k] = int(s); ep[k] = o[i]; ei[k] = i; wt[k] = w[i - 1]; fd[k] = 0.0; ment += 1
                    sp[k] = o[i] - pos[k] * p.stop_atr * atr[i - 1]
                    if (pos[k] == 1 and lo[i] <= sp[k]) or (pos[k] == -1 and hi[i] >= sp[k]):   # stopped on entry bar
                        r = pos[k] * (sp[k] / ep[k] - 1) - cost
                        trades.append((k, idx[i], idx[i], pos[k], ep[k], sp[k], wt[k], r, wt[k] * r))
                        mpnl += wt[k] * r; pos[k] = 0
    return pd.DataFrame(trades, columns=["sleeve", "entry", "exit", "dir", "entry_px", "exit_px", "weight", "ret", "pnl"])

def monthly_table(tr, start=START, end=END):
    ix = pd.period_range(start.tz_localize(None), (end - pd.Timedelta(minutes=1)).tz_localize(None), freq="M")
    pe = tr.exit.dt.tz_localize(None).dt.to_period("M"); pn = tr.entry.dt.tz_localize(None).dt.to_period("M")
    t = pd.DataFrame({"trades": tr.groupby(pn).size(), "pnl_pct": tr.groupby(pe).pnl.sum() * 100,
                      "wins": tr[tr.pnl > 0].groupby(pe).size(), "closed": tr.groupby(pe).size()}).reindex(ix).fillna(0)
    t["trades"] = t.trades.astype(int); t["win_rate"] = (t.wins / t.closed.replace(0, np.nan) * 100).round(0)
    return t[["trades", "pnl_pct", "win_rate"]]

def summary(tr, start=START, end=END):
    t = monthly_table(tr, start, end); eq = tr.sort_values("exit").pnl.cumsum()
    gp = tr.pnl[tr.pnl > 0].sum(); gl = -tr.pnl[tr.pnl < 0].sum()
    return dict(trades=len(tr), months=len(t), months_pos=int((t.pnl_pct > 0).sum()),
                pct_pos=float(round((t.pnl_pct > 0).mean() * 100, 1)), min_trades_month=int(t.trades.min()),
                total_pct=float(round(t.pnl_pct.sum(), 1)), worst_month=float(round(t.pnl_pct.min(), 1)),
                best_month=float(round(t.pnl_pct.max(), 1)), trade_win_rate=float(round((tr.pnl > 0).mean() * 100, 1)),
                profit_factor=float(round(gp / gl, 2)), max_dd_pct=float(round((eq.cummax() - eq).max() * 100, 1)))

if __name__ == "__main__":
    p = Params(); print(asdict(p))
    for s in ["BTCUSDT", "ETHUSDT"]:
        d = load(s, p.tf); tr = backtest(d, p); tr.to_csv(f"results/s3_{s}_trades.csv", index=False)
        print(f"\n===== {s} ====="); print(monthly_table(tr).round(2).to_string()); print(summary(tr))
        h = backtest(d, p, HOLD_START, START)
        print("--- holdout 2022-11-12 -> 2024-11-11 ---")
        print(monthly_table(h, HOLD_START, START).round(2).to_string()); print(summary(h, HOLD_START, START))
