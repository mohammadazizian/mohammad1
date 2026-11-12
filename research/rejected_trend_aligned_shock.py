"""
Trend-Aligned Shock Breakout with Monthly Governor  --  BTCUSDT / ETHUSDT perpetuals, 15-minute bars.

A 1-hour shock (|move| > z sigmas) is traded WITH the move, but only when it points the same way as the
trend of the preceding `trend` bars (default 7 days).  Counter-trend shocks are ignored.
Hold for a fixed time; no stop loss.  One position at a time.

Orders are market orders at the open of the bar after the signal bar.  Sizing is volatility-targeted.
A monthly governor stops new entries for the rest of the calendar month once realised PnL >= month_target.
Costs: 0.04 % taker fee + 0.01 % slippage per side, plus actual funding.
"""
from dataclasses import dataclass, asdict
import numpy as np, pandas as pd

@dataclass
class Params:
    tf: str = "15min"
    sleeves: tuple = ((4, 4.0, 672, 48),)         # (shock look-back bars, z threshold, trend bars, hold bars)
    vol_win: int = 96 * 7
    vol_target: float = 0.02; w_max: float = 1.0
    month_target: float = 0.02
    fee: float = 0.0004; slip: float = 0.0001

START = pd.Timestamp("2024-11-12", tz="UTC"); END = pd.Timestamp("2026-11-12", tz="UTC")
HOLD_START = pd.Timestamp("2022-11-12", tz="UTC")

def load(sym, tf="15min", path="data"):
    d = pd.read_parquet(f"{path}/{sym}_5m.parquet")
    return d.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                               "volume": "sum", "funding": "sum"})

def signals(d, p: Params):
    lc = np.log(d.close); sg = lc.diff().rolling(p.vol_win).std()
    sig = []
    for n, z, T, _ in p.sleeves:
        zz = (lc - lc.shift(n)) / (sg * np.sqrt(n))
        trend = np.sign(lc.shift(n) - lc.shift(n + T))                       # trend BEFORE the shock window
        sh = (zz > z).astype(int) - (zz < -z).astype(int)
        sig.append(sh.where(sh * trend > 0, 0).astype(int).values)
    w = (p.vol_target / (sg * np.sqrt(96))).clip(upper=p.w_max).fillna(0)
    return sig, [s[3] for s in p.sleeves], w.values

def backtest(d, p: Params = Params(), start=START, end=END):
    sig, hold, w = signals(d, p); K = len(sig)
    o = d.open.values; fund = d.funding.values; idx = d.index
    month = (idx.year * 12 + idx.month).values
    i0 = idx.searchsorted(start); i1 = idx.searchsorted(end); cost = 2 * (p.fee + p.slip)
    pos = [0] * K; ep = [0.0] * K; ei = [0] * K; wt = [0.0] * K; fd = [0.0] * K
    mpnl = 0.0; ment = 0; cur = -1; trades = []
    for i in range(i0, i1):
        if month[i] != cur: cur = month[i]; mpnl = 0.0; ment = 0
        for k in range(K):                                   # time exits at bar open
            if pos[k] != 0:
                fd[k] += fund[i] * pos[k]
                if i - ei[k] >= hold[k] or i == i1 - 1:
                    r = pos[k] * (o[i] / ep[k] - 1) - cost - fd[k]
                    trades.append((k, idx[ei[k]], idx[i], pos[k], ep[k], o[i], wt[k], r, wt[k] * r))
                    mpnl += wt[k] * r; pos[k] = 0
        if not (ment > 0 and mpnl >= p.month_target) and i < i1 - 1:
            for k in range(K):                               # entries from the previous bar's signal
                s = sig[k][i - 1]
                if pos[k] == 0 and s != 0 and w[i - 1] > 0:
                    pos[k] = int(s); ep[k] = o[i]; ei[k] = i; wt[k] = w[i - 1]; fd[k] = 0.0; ment += 1
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
        d = load(s, p.tf); tr = backtest(d, p); tr.to_csv(f"results/s4_{s}_trades.csv", index=False)
        print(f"\n===== {s} ====="); print(monthly_table(tr).round(2).to_string()); print(summary(tr))
        h = backtest(d, p, HOLD_START, START)
        print("--- holdout 2022-11-12 -> 2024-11-11 ---")
        print(monthly_table(h, HOLD_START, START).round(2).to_string()); print(summary(h, HOLD_START, START))
