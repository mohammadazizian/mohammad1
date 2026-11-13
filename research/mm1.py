# Step 1: SL/TP grid per strategy and coin, in R units (non-compounding, risk 1% per trade), split by period
import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
pd.set_option("display.width",250); pd.set_option("display.max_rows",400)
SLS=[0.005,0.0075,0.01,0.015,0.02,0.03]; TPS=[0.01,0.015,0.02,0.03,0.04,0.06,0.0]
rows=[]
for strat,sleeves,coins in [("S2",["S","F"],["BTCUSDT","ETHUSDT"]),("S3",["W"],["BTCUSDT","ETHUSDT","SOLUSDT"])]:
    for c in coins:
        for sl,tp in itertools.product(SLS,TPS):
            tr,_=run([(c,s) for s in sleeves],sl,tp,risk=0.01)
            R=tr.pnl/0.01; p1=R[tr.exit<MID]; p2=R[tr.exit>=MID]
            rows.append(dict(strat=strat,coin=c[:-4],sl=sl*100,tp=tp*100,n=len(tr),R1=round(p1.sum(),1),R2=round(p2.sum(),1),exp=round(R.mean(),3),
                             win=round((R>0).mean()*100),tp_hit=round((tr.kind=="tp").mean()*100),sl_hit=round((tr.kind=="sl").mean()*100)))
df=pd.DataFrame(rows); df["Rtot"]=df.R1+df.R2; df["Rmin"]=df[["R1","R2"]].min(axis=1); df.to_pickle("/home/user/mohammad1/research/mm1.pkl")
for (st,c),g in df.groupby(["strat","coin"]):
    print(f"\n{st} {c}: total R over 4y (rows SL%, cols TP%, 0=no TP)"); print(g.pivot(index="sl",columns="tp",values="Rtot").round(0).to_string())
    print("  worse-half R:"); print(g.pivot(index="sl",columns="tp",values="Rmin").round(0).to_string())
