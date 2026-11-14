"""
Shock & Flow Momentum with Monthly Governor  --  BTCUSDT / ETHUSDT perpetuals, 15-minute bars.

Two active sleeves, each holding at most one position (sleeves V and L are optional extras, off by default):

  S  Shock momentum : the last 1 h move exceeds z_shock sigmas  -> trade WITH the move, hold 12 h.
  F  Flow momentum  : 4 h net taker volume (buy - sell) is more than z_flow standard deviations away from
                      its 7-day mean -> trade WITH the flow, hold 12 h.

Orders are market orders at the open of the bar after the signal bar.  Sizing is volatility-targeted.
A monthly governor stops new entries for the rest of the calendar month once realised PnL >= month_target.
Costs: 0.04 % taker fee + 0.01 % slippage per side, plus actual funding.
"""
from dataclasses import dataclass, asdict
import numpy as np, pandas as pd

@dataclass
class Params:
    tf: str = "15min"
    s_on: bool = True; s_look: int = 4; s_z: float = 4.0; s_hold: int = 48
    f_on: bool = True; f_look: int = 16; f_z: float = 3.0; f_hold: int = 48
    v_on: bool = False; v_n: int = 96; v_z: float = 2.0; v_rv: float = 1.2; v_hold: int = 48
    l_on: bool = False; l_look: int = 16; l_z: float = 4.0; l_hold: int = 48
    vol_win: int = 96 * 7
    vol_target: float = 0.02; w_max: float = 1.0
    month_target: float = 0.01
    fee: float = 0.0004; slip: float = 0.0001

START = pd.Timestamp("2024-11-12", tz="UTC"); END = pd.Timestamp("2026-11-12", tz="UTC")

def load(sym, tf="15min", path="data"):
    d = pd.read_parquet(f"{path}/{sym}_5m.parquet")
    return d.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                               "volume": "sum", "taker_buy_base": "sum", "funding": "sum"})

def signals(d, p: Params):
    lc = np.log(d.close); sg = lc.diff().rolling(p.vol_win).std()
    z = (lc - lc.shift(p.s_look)) / (sg * np.sqrt(p.s_look))
    sS = (z > p.s_z).astype(int) - (z < -p.s_z).astype(int)
    flow = (2 * d.taker_buy_base - d.volume).rolling(p.f_look).sum()
    fz = (flow - flow.rolling(p.vol_win).mean()) / flow.rolling(p.vol_win).std()
    sF = (fz > p.f_z).astype(int) - (fz < -p.f_z).astype(int)
    w = (p.vol_target / (sg * np.sqrt(96))).clip(upper=p.w_max).fillna(0)
    bz = (d.close - d.close.rolling(p.v_n).mean()) / d.close.rolling(p.v_n).std()
    hv = lc.diff().rolling(96).std() / sg > p.v_rv
    sV = ((bz > p.v_z) & hv).astype(int) - ((bz < -p.v_z) & hv).astype(int)
    sV = sV.where(sV != sV.shift(1), 0)
    zl = (lc - lc.shift(p.l_look)) / (sg * np.sqrt(p.l_look))
    sL = (zl.abs() > p.l_z).astype(int)
    return ([sS.values * p.s_on, sF.values * p.f_on, sV.values * p.v_on, sL.values * p.l_on],
            [p.s_hold, p.f_hold, p.v_hold, p.l_hold], w.values)

def backtest(d, p: Params = Params(), start=START, end=END):
    sig, hold, w = signals(d, p); names = "SFVL"; K = len(sig)
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
                    trades.append((names[k], idx[ei[k]], idx[i], pos[k], ep[k], o[i], wt[k], r, wt[k] * r))
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
        tr = backtest(load(s, p.tf), p); tr.to_csv(f"results/s2_{s}_trades.csv", index=False)
        print(f"\n===== {s} ====="); print(monthly_table(tr).round(2).to_string()); print(summary(tr))
        HS = pd.Timestamp("2022-11-12", tz="UTC"); h = backtest(load(s, p.tf), p, HS, START)
        print(f"--- holdout 2022-11-12 -> 2024-11-11 (not used for design) ---")
        print(monthly_table(h, HS, START).round(2).to_string()); print(summary(h, HS, START))
