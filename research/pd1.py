import itertools
from pd_lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",400)
P0=pd.Timestamp("2022-11-12",tz="UTC"); MID=START
PP={s:prep(s) for s in ["BTCUSDT","ETHUSDT"]}
rows=[]
cfgs=[dict(mode=0,stop_k=k,tgt=0,hold=H,maxtr=mt) for k in [0,2,4] for H in [0,16,48,96] for mt in [1,2]]
cfgs+=[dict(mode=1,m=m,stop_k=k,tgt=t,hold=H,maxtr=mt) for m in [1,4,8] for k in [0.,0.5] for t in [0,1,2,-1,-2] for H in [0,48] for mt in [1,2]]
for cf in cfgs:
    r=dict(cf)
    for s,P in PP.items():
        for tag,(a,b) in {"p1":(P0,MID),"p2":(MID,END)}.items():
            tr=bt(P,a,b,**cf); pos,mc,tot,w=mstats(tr,a,b)
            r[f"{s[:3]}_{tag}"]=tot; r[f"{s[:3]}_{tag}_pos"]=pos; r[f"{s[:3]}_{tag}_n"]=len(tr)
    rows.append(r)
df=pd.DataFrame(rows); c4=["BTC_p1","BTC_p2","ETH_p1","ETH_p2"]; df["min4"]=df[c4].min(axis=1); df["sum4"]=df[c4].sum(axis=1)
df.to_pickle("pd1.pkl")
print("no governor. configs:",len(df),"frac all4>0:",(df.min4>0).mean().round(3))
print(df.groupby("mode")[c4+["sum4"]].mean().round(1))
cols=["mode","m","stop_k","tgt","hold","maxtr","BTC_p1_n"]+c4+["BTC_p1_pos","BTC_p2_pos","ETH_p1_pos","ETH_p2_pos","min4"]
print(df.sort_values("min4",ascending=False)[cols].head(25).to_string(index=False))
