"""
Session-Reversion Ensemble with Monthly Risk Governor  --  BTCUSDT / ETHUSDT perpetuals, 15-minute bars.

Independent "sleeves" (sub-strategies), each holding at most one position (A and D are active, B is optional/off):

  A  Weekend-gap fade   : Monday 06:00 UTC, fade the move made since Friday 21:00 UTC; hold 60 h.
  D  US-session fade    : every day 19:00 UTC, fade the last 8 h move if it exceeds 0.5 sigma; hold 24 h.
  B  Shock rebound      : after a 4 h move larger than 4 sigma (either direction) go long; hold 12 h.

All orders are market orders at the open of the bar following the signal bar (no look-ahead).
Position size per sleeve is volatility-targeted.  A monthly governor stops opening new trades for the
rest of the calendar month once realised month-to-date PnL reaches +month_target (positions already open
run to their normal time exit).

Costs: 0.04 % taker fee + 0.01 % slippage per side, plus actual funding payments.
"""
from dataclasses import dataclass, asdict
import numpy as np, pandas as pd

@dataclass
class Params:
    tf: str = "15min"
    # sleeve A - weekend gap fade
    a_on: bool = True
    a_ref_dow: int = 4; a_ref_hour: int = 21      # Friday 21:00 UTC reference price
    a_ent_dow: int = 0; a_ent_hour: int = 6       # Monday 06:00 UTC entry
    a_hold: int = 240                             # bars (60 h)
    a_thr: float = 0.0                            # min |move| in sigma units
    # sleeve D - daily US-session fade
    d_on: bool = True
    d_hour: int = 19; d_look: int = 32; d_thr: float = 0.5; d_hold: int = 96
    # sleeve B - shock rebound (long only)
    b_on: bool = False                            # optional third sleeve, disabled in the final configuration
    b_look: int = 16; b_z: float = 4.0; b_hold: int = 48
    # sizing / risk
    vol_win: int = 96 * 7                         # bars for sigma estimate
    vol_target: float = 0.02                      # target daily vol per sleeve (fraction of equity)
    w_max: float = 1.0                            # max notional per sleeve (x equity)
    stop_sigma: float = 0.0                       # per-trade stop distance in daily sigmas (0 = off)
    month_target: float = 0.025                   # stop new entries once month PnL >= this
    month_loss: float = 1.00                      # optional monthly loss lock (1.0 = disabled)
    fee: float = 0.0004; slip: float = 0.0001     # per side

START = pd.Timestamp("2024-11-12", tz="UTC"); END = pd.Timestamp("2026-11-12", tz="UTC")

def load(sym, tf="15min", path="data"):
    d = pd.read_parquet(f"{path}/{sym}_5m.parquet")
    if tf != "5min":
        d = d.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                "volume": "sum", "funding": "sum"})
    return d

def signals(d, p: Params):
    """Signals are evaluated on the close of bar i and executed at the open of bar i+1."""
    lc = np.log(d.close); sg = lc.diff().rolling(p.vol_win).std()
    idx = d.index; dow = idx.dayofweek; hr = idx.hour; mn = idx.minute
    last = (mn == 60 - int(pd.Timedelta(p.tf).total_seconds() // 60))        # last bar of an hour
    def at(dow_, hour):                                                      # bar closing exactly at dow/hour:00
        h = (hour - 1) % 24; dd = dow_ if hour > 0 else (dow_ - 1) % 7
        return (dow == dd) & (hr == h) & last
    # A
    ref = d.close.where(at(p.a_ref_dow, p.a_ref_hour)).ffill()
    nb = ((p.a_ent_dow - p.a_ref_dow) % 7 * 24 + p.a_ent_hour - p.a_ref_hour) * 4
    mv = (lc - np.log(ref)) / (sg * np.sqrt(nb))
    t = at(p.a_ent_dow, p.a_ent_hour)
    sA = -(((mv > p.a_thr) & t).astype(int) - ((mv < -p.a_thr) & t).astype(int))
    # D
    mv = (lc - lc.shift(p.d_look)) / (sg * np.sqrt(p.d_look))
    t = (hr == (p.d_hour - 1) % 24) & last
    sD = -(((mv > p.d_thr) & t).astype(int) - ((mv < -p.d_thr) & t).astype(int))
    # B
    z = (lc - lc.shift(p.b_look)) / (sg * np.sqrt(p.b_look))
    sB = (z.abs() > p.b_z).astype(int)
    w = (p.vol_target / (sg * np.sqrt(96))).clip(upper=p.w_max)
    dsig = (sg * np.sqrt(96)).fillna(0).values
    return sA.values * p.a_on, sD.values * p.d_on, sB.values * p.b_on, w.fillna(0).values, dsig

def backtest(d, p: Params = Params(), start=START, end=END):
    sA, sD, sB, w, dsig = signals(d, p)
    sig = [sA, sD, sB]; hold = [p.a_hold, p.d_hold, p.b_hold]; names = "ADB"
    o = d.open.values; hi = d.high.values; lo = d.low.values; fund = d.funding.values; idx = d.index
    month = (idx.year * 12 + idx.month).values
    i0 = idx.searchsorted(start); i1 = idx.searchsorted(end)
    cost = 2 * (p.fee + p.slip)
    pos = [0, 0, 0]; sp = [0.0] * 3; ep = [0.0] * 3; ei = [0] * 3; wt = [0.0] * 3; fd = [0.0] * 3
    mpnl = 0.0; ment = 0; cur = -1; trades = []
    for i in range(i0, i1):
        if month[i] != cur: cur = month[i]; mpnl = 0.0; ment = 0
        for k in range(3):                                   # exits from positions opened on earlier bars
            if pos[k] != 0:
                fd[k] += fund[i] * pos[k]
                xp = 0.0
                if i - ei[k] >= hold[k] or i == i1 - 1: xp = o[i]                 # time exit at bar open
                if p.stop_sigma > 0:                                               # protective stop (gap-aware)
                    if pos[k] == 1 and o[i] <= sp[k]: xp = o[i]
                    elif pos[k] == -1 and o[i] >= sp[k]: xp = o[i]
                    elif xp == 0.0 and pos[k] == 1 and lo[i] <= sp[k]: xp = sp[k]
                    elif xp == 0.0 and pos[k] == -1 and hi[i] >= sp[k]: xp = sp[k]
                if xp != 0.0:
                    r = pos[k] * (xp / ep[k] - 1) - cost - fd[k]
                    trades.append((names[k], idx[ei[k]], idx[i], pos[k], ep[k], xp, wt[k], r, wt[k] * r))
                    mpnl += wt[k] * r; pos[k] = 0
        locked = (ment > 0 and mpnl >= p.month_target) or mpnl <= -p.month_loss
        if not locked and i < i1 - 1:
            for k in range(3):                               # entries from the previous bar's signal
                s = sig[k][i - 1]
                if pos[k] == 0 and s != 0 and w[i - 1] > 0:
                    pos[k] = int(s); ep[k] = o[i]; ei[k] = i; wt[k] = w[i - 1]; fd[k] = 0.0; ment += 1
                    sp[k] = o[i] * (1 - pos[k] * p.stop_sigma * dsig[i - 1])
    return pd.DataFrame(trades, columns=["sleeve", "entry", "exit", "dir", "entry_px", "exit_px", "weight", "ret", "pnl"])

MONTHS = pd.period_range("2024-11", "2026-11", freq="M")
def monthly_table(tr):
    pe = tr.exit.dt.tz_localize(None).dt.to_period("M"); pn = tr.entry.dt.tz_localize(None).dt.to_period("M")
    t = pd.DataFrame({"trades": tr.groupby(pn).size(), "pnl_pct": tr.groupby(pe).pnl.sum() * 100,
                      "wins": tr[tr.pnl > 0].groupby(pe).size(), "closed": tr.groupby(pe).size()}).reindex(MONTHS).fillna(0)
    t["trades"] = t.trades.astype(int); t["win_rate"] = (t.wins / t.closed.replace(0, np.nan) * 100).round(0)
    return t[["trades", "pnl_pct", "win_rate"]]

def summary(tr):
    t = monthly_table(tr); eq = tr.sort_values("exit").pnl.cumsum()
    gp = tr.pnl[tr.pnl > 0].sum(); gl = -tr.pnl[tr.pnl < 0].sum()
    return dict(trades=len(tr), months=len(t), months_pos=int((t.pnl_pct > 0).sum()),
                pct_pos=round((t.pnl_pct > 0).mean() * 100, 1), min_trades_month=int(t.trades.min()),
                total_pct=round(t.pnl_pct.sum(), 1), worst_month=round(t.pnl_pct.min(), 1), best_month=round(t.pnl_pct.max(), 1),
                trade_win_rate=round((tr.pnl > 0).mean() * 100, 1), profit_factor=round(gp / gl, 2),
                max_dd_pct=round((eq.cummax() - eq).max() * 100, 1))

def anniversary_months(tr):
    """Alternative bucketing: the 24 months running from the 12th to the 11th."""
    e = (tr.exit - pd.Timedelta(days=11)).dt.tz_localize(None).dt.to_period("M")
    n = (tr.entry - pd.Timedelta(days=11)).dt.tz_localize(None).dt.to_period("M")
    ix = pd.period_range("2024-11", "2026-10", freq="M")
    return int((tr.groupby(e).pnl.sum().reindex(ix).fillna(0) > 0).sum()), int(tr.groupby(n).size().reindex(ix).fillna(0).min())

if __name__ == "__main__":
    p = Params(); print(asdict(p))
    for s in ["BTCUSDT", "ETHUSDT"]:
        tr = backtest(load(s, p.tf), p); tr.to_csv(f"results/{s}_trades.csv", index=False)
        t = monthly_table(tr); t.to_csv(f"results/{s}_monthly.csv")
        print(f"\n===== {s} ====="); print(t.round(2).to_string()); print({k: (float(v) if isinstance(v, float) else v) for k, v in summary(tr).items()})
        print("anniversary months (12th->11th): profitable %d/24, min trades in a month %d" % anniversary_months(tr))
