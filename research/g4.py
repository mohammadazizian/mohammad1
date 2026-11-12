import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from strategy2 import *
from dataclasses import replace
D={s:load(s,"15min","/home/user/mohammad1/data") for s in ["BTCUSDT","ETHUSDT"]}
HS=pd.Timestamp("2022-11-12",tz="UTC"); HE=START
def line(tag,p):
    out=[f"{tag:26s}"]
    for s,d in D.items():
        a=summary(backtest(d,p)); b=summary(backtest(d,p,HS,HE),HS,HE)
        out.append(f"{s[:3]} NOW {a['months_pos']:2d}/25 mt {a['min_trades_month']} tot {a['total_pct']:6.1f} w {a['worst_month']:6.1f} PF {a['profit_factor']:.2f} n {a['trades']:3d} || HOLD {b['months_pos']:2d}/25 mt {b['min_trades_month']} tot {b['total_pct']:6.1f} w {b['worst_month']:6.1f} |")
    print(" ".join(out),flush=True)
if __name__=="__main__":
    for v,l in [(0,0),(1,0),(0,1),(1,1)]:
        for T in [0.015,0.02,0.03]:
            for vt in [0.02]:
                line(f"V{v} L{l} T{T}",Params(v_on=bool(v),l_on=bool(l),month_target=T))
        line(f"V{v} L{l} nogov",Params(v_on=bool(v),l_on=bool(l),month_target=9))
