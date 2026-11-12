import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from strategy4 import *
from dataclasses import replace
D={s:load(s,"15min","/home/user/mohammad1/data") for s in ["BTCUSDT","ETHUSDT"]}
def line(tag,p):
    out=[f"{tag:34s}"]
    for s,d in D.items():
        a=summary(backtest(d,p)); b=summary(backtest(d,p,HOLD_START,START),HOLD_START,START)
        out.append(f"{s[:3]} NOW {a['months_pos']:2d}/25 mt {a['min_trades_month']} tot {a['total_pct']:6.1f} w {a['worst_month']:6.1f} PF {a['profit_factor']:.2f} n {a['trades']:3d} || HOLD {b['months_pos']:2d}/25 mt {b['min_trades_month']} tot {b['total_pct']:6.1f} w {b['worst_month']:6.1f} |")
    print(" ".join(out),flush=True)
if __name__=="__main__":
    for T in [9,0.0075,0.01,0.015,0.02,0.03]: line(f"n4 z4 T672 H48 gov{T}",Params(month_target=T))
    for T in [9,0.01,0.02]: line(f"n4 z4 T288 H48 gov{T}",Params(sleeves=((4,4.,288,48),),month_target=T))
    for T in [9,0.01,0.02]: line(f"n4 z4 T672 H96 gov{T}",Params(sleeves=((4,4.,672,96),),month_target=T))
    for T in [9,0.01,0.02]: line(f"n4 z3.5 T672 H48 gov{T}",Params(sleeves=((4,3.5,672,48),),month_target=T))
    for T in [9,0.01,0.02]: line(f"n4 z3 T672 H48 gov{T}",Params(sleeves=((4,3.,672,48),),month_target=T))
