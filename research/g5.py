import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from strategy3 import *
from dataclasses import replace
D={s:load(s,"15min","/home/user/mohammad1/data") for s in ["BTCUSDT","ETHUSDT"]}
def line(tag,p):
    out=[f"{tag:44s}"]; ok=True
    for s,d in D.items():
        a=summary(backtest(d,p)); b=summary(backtest(d,p,HOLD_START,START),HOLD_START,START)
        out.append(f"{s[:3]} NOW {a['months_pos']:2d}/25 mt {a['min_trades_month']} tot {a['total_pct']:6.1f} w {a['worst_month']:6.1f} PF {a['profit_factor']:.2f} n {a['trades']:3d} || HOLD {b['months_pos']:2d}/25 mt {b['min_trades_month']} tot {b['total_pct']:6.1f} w {b['worst_month']:6.1f} |")
    print(" ".join(out),flush=True)
if __name__=="__main__":
    b=Params(); line("base",b); line("no governor",replace(b,month_target=9))
    for T in [0.005,0.0075,0.0125,0.015,0.02]: line(f"T {T}",replace(b,month_target=T))
    for z in [1.5,1.75,2.25,2.5]: line(f"z {z}",replace(b,sleeves=((4,z,96),)))
    for n in [3,6,8]: line(f"look {n}",replace(b,sleeves=((n,2.,96),)))
    for h in [64,80,112,144]: line(f"hold {h}",replace(b,sleeves=((4,2.,h),)))
    for a in [3,5,6]: line(f"stop_atr {a}",replace(b,stop_atr=a))
    for sl in [0.0003,0.0005]: line(f"slip {sl}",replace(b,slip=sl))
