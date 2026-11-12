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
    b=Params()
    line("base",b); line("no governor",replace(b,month_target=9)); line("S only nogov",replace(b,f_on=False,month_target=9)); line("F only nogov",replace(b,s_on=False,month_target=9))
    for T in [0.015,0.02,0.025,0.04,0.05]: line(f"T {T}",replace(b,month_target=T))
    for z in [3,3.5,4.5,5]: line(f"s_z {z}",replace(b,s_z=z))
    for z in [2.5,3.5]: line(f"f_z {z}",replace(b,f_z=z))
    for h in [32,64,96]: line(f"hold {h}",replace(b,s_hold=h,f_hold=h))
    for l in [3,6,8]: line(f"s_look {l}",replace(b,s_look=l))
    for l in [12,24]: line(f"f_look {l}",replace(b,f_look=l))
    for sl in [0.0003,0.0005]: line(f"slip {sl}",replace(b,slip=sl))
