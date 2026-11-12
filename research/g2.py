import sys; sys.path.insert(0,"/home/user/mohammad1"); sys.path.insert(0,"/home/user/mohammad1/research")
from g1 import *
def roll24(tr):
    # anniversary months: 12th -> 11th
    e=(tr.exit-pd.Timedelta(days=11)).dt.tz_localize(None).dt.to_period("M"); n=(tr.entry-pd.Timedelta(days=11)).dt.tz_localize(None).dt.to_period("M")
    idx=pd.period_range("2024-11","2026-10",freq="M")
    return int((tr.groupby(e).pnl.sum().reindex(idx).fillna(0)>0).sum()), int(tr.groupby(n).size().reindex(idx).fillna(0).min())
def line(tag,p):
    out=[f"{tag:34s}"]
    for s,d in D.items():
        tr=backtest(d,p); sm=summary(tr); r=roll24(tr)
        y1=tr[tr.exit<"2025-11-12"].pnl.sum()*100; y2=tr[tr.exit>="2025-11-12"].pnl.sum()*100
        out.append(f"{s[:3]} pos {sm['months_pos']}/25 minTr {sm['min_trades_month']} tot {sm['total_pct']:6.1f} (y1 {y1:5.1f} y2 {y2:5.1f}) worst {sm['worst_month']:6.1f} dd {sm['max_dd_pct']:5.1f} PF {sm['profit_factor']:.2f} n {sm['trades']} |")
    print(" ".join(out))
for T in [0.02,0.03]:
    b=Params(b_on=False,month_target=T,month_loss=1.0)
    print(f"--- base AD, T={T}")
    line("base",b); line("no governor",replace(b,month_target=9))
    for sl in [0.0002,0.0003,0.0005]: line(f"slip {sl}",replace(b,slip=sl))
    for T2 in [0.015,0.025,0.035,0.04,0.05]: line(f"T {T2}",replace(b,month_target=T2))
    for h in [17,18,20,21]: line(f"d_hour {h}",replace(b,d_hour=h))
    for L in [24,40,48]: line(f"d_look {L}",replace(b,d_look=L))
    for th in [0,0.25,0.75,1.0]: line(f"d_thr {th}",replace(b,d_thr=th))
    for H in [64,80,112]: line(f"d_hold {H}",replace(b,d_hold=H))
    for H in [192,216,264,288]: line(f"a_hold {H}",replace(b,a_hold=H))
    for h in [4,5,7,8]: line(f"a_ent_hour {h}",replace(b,a_ent_hour=h))
    for h in [20,22]: line(f"a_ref_hour {h}",replace(b,a_ref_hour=h))
    for v in [0.015,0.03]: line(f"vol_target {v} (T scaled)",replace(b,vol_target=v,month_target=T*v/0.02))
    line("with B sleeve",replace(b,b_on=True)); line("A only",replace(b,d_on=False)); line("D only",replace(b,a_on=False))
