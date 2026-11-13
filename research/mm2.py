import sys; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
pd.set_option("display.width",250)
S2=[("BTCUSDT","S"),("BTCUSDT","F"),("ETHUSDT","S"),("ETHUSDT","F")]; SL2={"BTCUSDT":0.01,"ETHUSDT":0.015}; TP2={"BTCUSDT":0.04,"ETHUSDT":0.06}
S3=[("BTCUSDT","W"),("ETHUSDT","W"),("SOLUSDT","W")]; SL3={"BTCUSDT":0.0075,"ETHUSDT":0.01,"SOLUSDT":0.015}; TP3={"BTCUSDT":0.045,"ETHUSDT":0.06,"SOLUSDT":0.09}
def rstats(tr,tag):
    R=tr.pnl/0.01
    for st,g in R.groupby(tr.stream):
        t=tr[tr.stream==st]; print(f"  {tag} {st:6s} n {len(g):4d} win {(g>0).mean()*100:4.0f}% avgR {g.mean():+.3f} totR {g.sum():6.1f}  R(22-24) {g[t.exit<MID].sum():6.1f} R(24-26) {g[t.exit>=MID].sum():6.1f}  exits tp/sl/time {int((t.kind=='tp').sum())}/{int((t.kind=='sl').sum())}/{int((t.kind=='time').sum())}")
    print(f"  {tag} ALL    n {len(R):4d} win {(R>0).mean()*100:4.0f}% avgR {R.mean():+.3f} sdR {R.std():.2f} kelly-ish risk/trade {R.mean()/R.var()*100:.1f}%  PF {R[R>0].sum()/-R[R<0].sum():.2f}")
a,_=run(S2,SL2,TP2,risk=0.01); b,_=run(S3,SL3,TP3,risk=0.01)
print("Per-trade statistics in R (1R = amount risked), fixed size:"); rstats(a,"S2"); rstats(b,"S3")
